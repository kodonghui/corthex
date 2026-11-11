# Writing for a learner

The reader is a high-school student who has followed the course so far and reads carefully. Write so that they never need to look a word up and never read a sentence that says nothing.

## Detailed, with nothing extra

- Each sentence does one job: it answers, explains why, shows evidence, gives an example or states a limit. Delete a sentence that does none of these.
- Delete announcements ("this section looks at"), accounts of your own process ("first I searched"), filler links ("in conclusion", "for reference"), empty emphasis ("very important") and hedges with no content ("it can be said that").
- Detailed means more steps, cases and numbers, not more words. Where a step is missing the reader stops, so add the step.
- One idea per sentence, with the subject close to its verb. Split a sentence that needs a second clause to be understood.
- Start each paragraph with its claim, then give the evidence or the example.

## Plain words

- Define each term in plain words where it first appears, then use the same term every time. Do not switch between synonyms for one idea.
- Give the original term once for a standard term, such as `recall`, `AUROC` or `Send`, and say what an abbreviation stands for.
- Give one everyday example for each hard idea, then return to the real case in the same paragraph. The example explains the mechanism; it does not replace it.
- When the learner has a frame they prefer for new concepts, such as conditions, then effects, then exceptions, use it for every new concept.
- Math: say it in words, write the formula, name each symbol, then work one example with real numbers.
- Numbers carry their unit and their base: "70% of the 145 hidden-rule questions", not "70%". Round the same way across the page.
- Replace vague words, such as various, appropriate, effective or optimal, with the thing or the number.

## Natural language

Write the sentence a careful native speaker would write. When the document is not in English, think in its language rather than translating English word for word.

- Keep the field's standard terms, in the title and in the text, so that the reader recognises them in other sources. Never replace a standard term with a coined native word or a metaphor. Plain enough for a high-school student means explaining the standard term where it first appears, not renaming it.
- No made-up words or compounds. When the language has no common word for an idea, use the original term with a plain explanation.
- An analogy may explain a term in the text, after the term itself. It never becomes the name of the thing.
- Keep code, API names and file names in their original spelling, in code format.
- Read each sentence as if aloud, and rewrite any that a native speaker would not say.

### Korean

When `language` is `ko`, use polite speech (해요체 unless the profile says otherwise) and address the reader as the profile's `address_as`. Pure Korean (순한국말) is not the goal: keep a term that Korean sources use, including an English or Sino-Korean one, and explain it. Replace these patterns, which come from coining words or from translating English word for word:

| Instead of | Write |
| --- | --- |
| A coined word or a metaphor in place of a standard term, such as `관문` for gate criteria or `증거 사다리` for evidence levels | The standard term, explained where it first appears, such as `필수 조건(gate): 하나라도 못 넘으면 탈락` or `증거 수준 E0~E3` |
| A title made of such words, such as `관문과 증거 사다리` | A title that names the topic in standard terms, such as `채점 루브릭: 필수 조건과 증거 수준(E0~E3)` |
| A passive with `~에 의해` where the doer is known | An active sentence with the real subject |
| `~를 가지다` for "have", as in `의미를 가진다` | `~이다` or `~가 있다`, as in `뜻이다` |
| `~하는 것이 가능하다` | `~할 수 있다` |
| `~에 있어서`, `~에 대해서` piled up | Drop it, or name the relation |
| Stacked `~적`, as in `체계적인 효율적 관리` | The concrete word |
| `~을 통해` for every means | `~으로`, `~해서` |
| A sentence that opens with `그것은` or `이것은` | The noun itself |
| `~라고 할 수 있다` | The claim itself |

## Tags

Mark each claim so that the reader can tell what kind of statement it is. Put the tag at the start of the sentence or the bullet, in the document's language.

| Tag | In Korean | Meaning |
| --- | --- | --- |
| `[fact]` | `[사실]` | A source says it, and the source is in the evidence table |
| `[interpretation]` | `[해석]` | Your reading of facts or results |
| `[run]` | `[실행]` | You executed it, and the output says so |
| `[assumption]` | `[가정]` | A value you chose, such as a cost ratio or a made-up distribution |

## The last read

Read the page from the top as the learner. Mark every place where you would stop: a term not yet defined, a jump between steps, a number without its base, a sentence that says nothing. Fix each one, then read again.
