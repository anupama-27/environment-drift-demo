"""Hand labels for audit sample (a), written by the annotator after reading each response blind
(only question, gold and the last-number value were shown). Default GENUINE unless listed."""
G = ("GENUINE", "Ends with a complete concluding statement of this number as the answer.")
SPECIAL = {
    "A019": ("GENUINE", "Concludes 'Vincent saves $6.00'; the explanation names the wrong package as better value but the committed amount is right."),
    "A036": ("GENUINE", "Concludes 4 minutes; swaps who waits for whom, but the committed quantity is the asked one."),
    "A053": ("COINCIDENTAL", "Degenerate loop 'K = K + 21 \\implies ...' until the token limit; 21 is never concluded."),
    "A063": ("GENUINE", "Concludes 'Sandra ordered 160 red roses' and restates 'deliver all 160 red roses by 5 pm'."),
    "A065": ("COINCIDENTAL", "Wrong setup (6r = 160), then truncated mid-sentence; last number 5 is the hamster straw rate, not an answer."),
    "A070": ("GENUINE", "Ends 'So, James runs a total of 540 meters in a week.'"),
    "A071": ("GENUINE", "Concludes 6 female unicorns, then adds a generic closing paragraph without numbers."),
    "A081": ("COINCIDENTAL", "Commits to $15 but by two compensating errors (revenue = cost + profit = 30; lemons = $5/gal x 3); right number, wrong reasoning."),
    "A089": ("COINCIDENTAL", "Self-contradictory setup, truncated at 'the cost of lemons is'; 15 is the total-cost figure, no conclusion."),
    "A096": ("AMBIGUOUS", "Solves x = 18 correctly but is truncated at 'Therefore,' before stating the conclusion."),
    "A120": ("GENUINE", "Concludes '**Steve will be waiting 4 minutes longer than Tim**'; mislabels the waiter but commits to 4."),
}
# committed: does the response commit to gold as its final answer (independent of reasoning quality)?
NOT_COMMITTED = {"A053", "A065", "A089", "A096"}
