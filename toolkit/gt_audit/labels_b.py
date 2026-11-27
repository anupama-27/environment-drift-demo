"""Hand labels for audit sample (b), written blind (question, gold and full response only).
Label = does the response commit to the gold value as its final answer?
CREDIT / NO_CREDIT / AMBIGUOUS. Default CREDIT unless listed."""
DEFAULT = ("CREDIT", "Final stated answer (bold/boxed/'answer is'/conclusion) equals gold.")
SPECIAL = {
    "B006": ("CREDIT", "Box reads '40 - 36 = 4 minutes'; the committed value is the right-hand side 4."),
    "B025": ("CREDIT", "Commits to '**2 seconds**' (says the slower team wins, a wording slip; the asked margin is right)."),
    "B031": ("CREDIT", "Writes 17/8.5 ≈ 2 then states final answer **2**."),
    "B049": ("NO_CREDIT", "Final box is -$10 (negative change); the gold 10 appears only as a magnitude."),
    "B051": ("NO_CREDIT", "Final box is 230/v, an expression in an invented variable, not 230."),
    "B053": ("NO_CREDIT", "Final box is 42/13 after a wrong setup; 42 is only the numerator."),
}
for _i in (42, 43, 44, 45, 46, 47, 48, 50, 52):
    SPECIAL[f"B{_i:03d}"] = ("NO_CREDIT", "Final box is 294n (invented variable n = number of chickens); not the number 294.")
