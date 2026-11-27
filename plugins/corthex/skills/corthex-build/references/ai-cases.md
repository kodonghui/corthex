# Test cases for AI behaviour

Read this in stage 12 when a behaviour of the product calls an AI model. The stage's steps, results and gate are in [12-qa.md](12-qa.md); the step numbers and the stage 11 rules that this text names are those of that file and of [ai-calls.md](ai-calls.md).

## Cases

For a behaviour that calls an AI model, add cases with questions inside its scope and outside it, such as an unrelated request or one that asks it to ignore its rules. Expect what its AI call entry (stage 04) says: the output format, the server's checks, and that the data marked as not sent never reaches the model. Use scripted fakes for delay, timeout, refusal, malformed output and provider failures, and verify that unrelated operations remain responsive and refused requests change no data. Fixed answers alone do not exercise these failure paths. Most answer cases can run against recorded answers through the fake client (stage 11); mark the ones that call the real model, since they cost money and their answers vary, and run them only when asked, with a key set. To judge the real model's answers, run each case at least three times and report pass@1 together with pass^k, the share of cases that pass every run. Compare a change with runs before and after it on the same cases and scripts, pair by pair; grade by the state of the data, such as what was saved or submitted, not by the wording; and use the production model settings file with a separate test key and development or staging targets (step 7). Keep a regression set of cases that pass apart from a capability set of cases to improve, and add real failures to them. Check a model grader against a sample graded by people, and report the number of runs and the uncertainty; the product sets the counts, with at least three runs per case. Before running real-model cases, check the test key's balance and limit (stage 11). When the model holds write tools, add cases of impersonation, someone else's evidence and instructions inside an attachment or a tool result. When it talks with people or holds tools, also run the red-team cases below in this file.

## Red-team cases

For a product whose AI talks with people or holds tools:

1. Choose the categories that apply, and give the reason for each one left out: direct injection, indirect injection, impersonation and identity bypass, fake evidence, social engineering, financial fraud, personal data, unreasonable demands, crisis signals, and runaway or false answers.
2. For each category, write scenarios over several turns, with pressure and attachments.
3. Judge the answer and the tool calls together.
4. Run each scenario three times; one break is a failure.
5. Run them again whenever the prompt, the knowledge or the model changes.
6. For crisis signals, check the contacts and the laws for the country and the date.
