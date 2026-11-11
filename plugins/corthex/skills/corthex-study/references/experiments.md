# Measured experiments

Run an experiment when the question is how models or tools actually behave and the answer depends on numbers: which threshold, which prompt, which model, how stable. When official documents or a cheap simulation settle the question, do not spend money on it.

## Before the first call

- Get the user's permission for paid calls in their own words, with the models and the budget. Estimate the cost first: calls × tokens × the price on the official price page, with the date you read it.
- Take keys from environment variables or from a file the user pointed to. Check that a key is present, never what it is. Never print a key, and never write it into a log, a command line, the page, the record or a commit. If a copy is needed, keep it in the session's scratch folder, readable by its owner only, and delete it at the end. If a key is exposed, tell the user to revoke it and issue a new one.
- Check each model's exact ID, its settings (effort or reasoning, structured output) and its price on the provider's current pages.
- Run five items first, to check parsing, the cost of one call and the time it takes.

## The labeled set

- Write the items from the learner's material, and label each with the answer the experiment checks. Say on the page who wrote the items and the labels, and that the real mix of cases will differ.
- Group the items by what matters to the question, and include enough of the hard group to measure it on its own, such as the cases a keyword rule cannot see.
- Size the set for the claim. To say "misses at most 1%" with 95% confidence and no misses, the set needs at least 299 items that should be caught. With fewer, report the bound the set supports.
- Keep the set as a file with stable IDs, so that every result traces back to its items.

## Runs

- Compare on the same items: the material's design, the instructor's suggestion and the alternatives. Change one thing at a time, such as the model, the prompt version or the effort, and keep the rest fixed.
- Ask for structured output with a schema, so that every answer parses. Count refusals and errors on their own; never fill them in.
- Retry rate limits and server errors with backoff, cap the number of calls in flight, and write each answer to a raw file as it arrives, so that a stopped run resumes.
- Record for each call: the model, its settings, tokens in and out, the time and the raw answer.
- Run part of the set again at least once, to measure how much the answers to identical calls change.
- Use the highest effort or the largest model as a comparison, and report whether it changed the result for its time and cost.

## Analysis

- Define each measure in plain words where the page first uses it, such as recall, false positive rate, AUROC and calibration error.
- Report the hard group on its own; an average can hide it.
- Choose thresholds on one half of the set and measure them on the other half. Repeat the split many times, such as 500, keeping each group's share, and report the mean.
- Give an upper bound for a rate measured on few items (Clopper-Pearson), and say when the set is too small for the claim.
- Before treating a model's stated probability as a probability, check its calibration: in bins, compare what it said with how often it was right.

## Report and clean up

- A table of setups by measures, the cost and time of every setup, and the total number of calls and the total cost.
- What was not measured, such as the quality of the answers after routing, and what the made-up set does to the result.
- Model IDs and prices, with the date they were checked.
- Delete key copies and temporary files at the end. Keep the item set, the scripts and the raw outputs, which hold no secrets.
