"""Any server that speaks the OpenAI chat completions API: Ollama, vLLM, LM Studio, llama.cpp
or a hosted endpoint. Standard library only.

The API key is read from the environment and is used for one thing, the Authorization header.
It is not part of describe(), of any error message, of the cache or of the run log.

DRIFTAUDIT_API_KEY goes to whatever endpoint is configured. OPENAI_API_KEY goes to
api.openai.com only, because most people have it exported for that service and would not
want it sent to a lab server or a gateway. Plain http is refused for anything but this
machine (localhost, 127.0.0.1, ::1) unless the caller allows it, since the key and the
prompts would cross the network unencrypted. Redirects are never followed.
"""
from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .. import __version__
from ..errors import DriftAuditError
from .base import Backend, Conversation

DEFAULT_BASE_URL = "https://api.openai.com/v1"
KEY_VARIABLES = ("DRIFTAUDIT_API_KEY", "OPENAI_API_KEY")
OPENAI_HOST = "api.openai.com"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
MAX_WAIT = 30.0
# Largest reply body read from the server. A chat completion is a few kilobytes.
MAX_RESPONSE_BYTES = 16 * 2 ** 20


class _Cancelled(Exception):
    """Another request of the same batch failed, so this one stops retrying."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib would resend the Authorization header to wherever the redirect points.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _key_from_environment(host: str) -> Tuple[Optional[str], Optional[str]]:
    """(key, name of the variable it came from) for requests to `host`."""
    names = KEY_VARIABLES if host.lower() == OPENAI_HOST else KEY_VARIABLES[:1]
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return None, None


def _is_loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _clean_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme not in ("http", "https") or not parts.hostname or port == -1:
        raise DriftAuditError(
            f"--base-url must look like http://localhost:11434/v1 or {DEFAULT_BASE_URL}; "
            f"got {base_url!r}.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise DriftAuditError(
            "--base-url must not carry credentials or a query string. Put the key in "
            f"{KEY_VARIABLES[0]} instead.")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    if port:
        host = f"{host}:{port}"
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, "", ""))


def _one_line(text: object, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


class OpenAICompatBackend(Backend):
    name = "openai"

    def __init__(self, model: str, base_url: str = DEFAULT_BASE_URL, concurrency: int = 8,
                 timeout: float = 120.0, max_retries: int = 4, backoff: float = 1.0,
                 allow_insecure_http: bool = False) -> None:
        super().__init__()
        if not model:
            raise DriftAuditError("The openai backend needs a model name: pass --model.")
        if concurrency < 1 or max_retries < 0 or timeout <= 0:
            raise DriftAuditError("concurrency must be at least 1, retries at least 0 and the "
                                  "timeout positive.")
        self.model = model
        self.base_url = _clean_base_url(base_url)
        self.concurrency = int(concurrency)
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.backoff = float(backoff)
        self._endpoint = self.base_url + "/chat/completions"
        parts = urllib.parse.urlsplit(self.base_url)
        host = parts.hostname or ""
        if parts.scheme == "http" and host.lower() not in LOCAL_HOSTS and not allow_insecure_http:
            raise DriftAuditError(
                f"--base-url {self.base_url} uses plain http to another machine, so the prompts and any "
                "API key would travel unencrypted. Use https, or pass --allow-insecure-http if the "
                "network is yours.")
        self._api_key, self.key_variable = _key_from_environment(host)
        self.key_host = host
        handlers: List[urllib.request.BaseHandler] = [_NoRedirect()]
        if _is_loopback(urllib.parse.urlsplit(self.base_url).hostname or ""):
            # A server on this machine is not reached through a proxy meant for the internet.
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)
        self._lock = threading.Lock()
        self._fingerprints: Dict[str, None] = {}
        self._served: Dict[str, None] = {}

    def describe(self) -> Dict[str, object]:
        info: Dict[str, object] = {"backend": self.name, "model": self.model, "base_url": self.base_url}
        with self._lock:
            served = sorted(name for name in self._served if name != self.model)
            fingerprints = sorted(self._fingerprints)
        if served:
            info["served_model"] = ",".join(served)
        if fingerprints:
            # More than one value means the serving stack changed while this object was in use.
            info["system_fingerprint"] = ",".join(fingerprints)
        return info

    @property
    def cache_id(self) -> str:
        # The same model name behind another address may be a different build or quantization.
        if self.base_url == DEFAULT_BASE_URL:
            return self.model
        return f"{self.model}@{self.base_url}"

    def _chat(self, conversations: List[Conversation], temperature: float,
              seeds: List[int], max_new_tokens: int) -> List[str]:
        stop = threading.Event()
        jobs = list(zip(conversations, seeds))
        if len(jobs) == 1 or self.concurrency == 1:
            return [self._complete(messages, temperature, seed, max_new_tokens, stop)
                    for messages, seed in jobs]
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(self.concurrency, len(jobs)))
        try:
            futures = [pool.submit(self._complete, messages, temperature, seed, max_new_tokens, stop)
                       for messages, seed in jobs]
            concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)
            for future in futures:
                error = future.exception() if future.done() else None
                if error is not None:
                    raise error
            return [future.result() for future in futures]
        finally:
            # After a failure the rest of the batch is abandoned: queued requests are dropped
            # and the ones in flight stop at their next retry.
            stop.set()
            pool.shutdown(wait=False, cancel_futures=True)

    def _complete(self, messages: Conversation, temperature: float, seed: int,
                  max_new_tokens: int, stop: threading.Event) -> str:
        payload: Dict[str, object] = {"model": self.model, "messages": messages,
                                      "temperature": temperature, "max_tokens": max_new_tokens}
        if temperature > 0:
            payload["seed"] = seed
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": f"driftaudit/{__version__}"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        failure = ""
        wait = 0.0
        for attempt in range(self.max_retries + 1):
            if stop.wait(wait):
                raise _Cancelled()
            wait = min(self.backoff * 2 ** attempt, MAX_WAIT)
            request = urllib.request.Request(self._endpoint, data=body, headers=headers, method="POST")
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise DriftAuditError(
                        f"{self.base_url} sent a reply larger than {MAX_RESPONSE_BYTES:,} bytes, which "
                        "is not a chat completion. Check --base-url.")
                data = json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                failure = self._http_failure(exc)
                wait = max(wait, _retry_after(exc))
                continue
            except (TimeoutError, socket.timeout):
                failure = f"no reply within {self.timeout:g} s"
                continue
            except urllib.error.URLError as exc:
                failure = self._redact(_one_line(getattr(exc.reason, "strerror", None) or exc.reason))
                continue
            except (OSError, http.client.HTTPException) as exc:
                failure = self._redact(_one_line(exc) or type(exc).__name__)
                continue
            except ValueError:
                failure = "the reply was not JSON"
                continue
            return self._reply(data)
        raise DriftAuditError(
            f"{self.base_url} gave no usable answer in {self.max_retries + 1} attempts "
            f"({failure}). Check that the server is running and that --base-url and --model are right.")

    def _http_failure(self, exc: urllib.error.HTTPError) -> str:
        """Reason to retry, or DriftAuditError when retrying cannot help."""
        status = exc.code
        detail = self._redact(_error_detail(exc))
        if status == 429 or status >= 500:
            return f"HTTP {status}" + (f": {detail}" if detail else "")
        if status in (401, 403):
            # The server's own message is left out: some servers echo part of the key.
            raise DriftAuditError(
                f"{self.base_url} refused the credentials (HTTP {status}). Set {KEY_VARIABLES[0]} "
                f"to a valid key ({KEY_VARIABLES[1]} is used only for {OPENAI_HOST}).")
        if 300 <= status < 400:
            raise DriftAuditError(
                f"{self.base_url} redirects elsewhere (HTTP {status}). Pass the final address "
                "as --base-url.")
        hint = " Check --base-url (it usually ends in /v1) and --model." if status == 404 else ""
        raise DriftAuditError(
            f"{self.base_url} rejected the request (HTTP {status})" + (f": {detail}" if detail else ".") + hint)

    def _reply(self, data: Any) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise DriftAuditError(
                f"{self.base_url} answered without choices[0].message.content. Is it an "
                "OpenAI-compatible chat completions endpoint?") from None
        with self._lock:
            fingerprint = data.get("system_fingerprint")
            if isinstance(fingerprint, str) and fingerprint:
                self._fingerprints[fingerprint] = None
            served = data.get("model")
            if isinstance(served, str) and served:
                self._served[served] = None
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content if isinstance(content, str) else ""

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "[key removed]")
        return text


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(4096).decode("utf-8", "replace")
    except (OSError, http.client.HTTPException):
        return ""
    try:
        error = json.loads(raw).get("error")
        message = error.get("message") if isinstance(error, dict) else error
    except (ValueError, AttributeError):
        message = raw
    return _one_line(message or "")


def _retry_after(exc: urllib.error.HTTPError) -> float:
    try:
        return min(max(float(exc.headers.get("Retry-After", "0")), 0.0), 60.0)
    except (TypeError, ValueError):
        return 0.0
