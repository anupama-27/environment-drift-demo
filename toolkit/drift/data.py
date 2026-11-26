"""GSM8K loading: first N items of each split, in the existing order (no resampling)."""
from . import config
from .extract import gold_answer


def dataset_revision():
    try:
        from huggingface_hub import HfApi
        return HfApi().dataset_info(config.DATASET_ID).sha
    except Exception as e:  # offline or mock run
        return f"unknown ({type(e).__name__})"


def model_revision():
    try:
        from huggingface_hub import HfApi
        return HfApi().model_info(config.MODEL_ID).sha
    except Exception as e:
        return f"unknown ({type(e).__name__})"


def load_items(split, n):
    """split: 'train' (development) or 'test' (evaluation)."""
    if config.BACKEND == "mock":
        return _mock_items(split, n)
    from datasets import load_dataset
    ds = load_dataset(config.DATASET_ID, config.DATASET_CONFIG, split=split)
    items = []
    for i in range(min(n, len(ds))):
        row = ds[i]
        items.append({
            "id": f"{split}-{i}",
            "question": row["question"],
            "gold": gold_answer(row["answer"]),
        })
    return items


def _mock_items(split, n):
    return [{"id": f"{split}-{i}", "question": f"What is {i} + {i + 1}?", "gold": float(2 * i + 1)}
            for i in range(n)]

