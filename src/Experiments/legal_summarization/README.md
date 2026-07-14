# Legal Summarization Evaluation

This experiment evaluates Artemis City's current Exo-backed summarization
stack against source/reference datasets. Benchmark outcomes are isolated in
`data/legal_summarization.db`; they do not train production Hebbian weights or
change agent trust.

## Quick start

Inspect five streamed rows without running inference:

```bash
python3 -m src.Experiments.legal_summarization.main \
  --dataset-source hub --streaming --describe
```

Run the dependency-free extractive baseline over ten rows:

```bash
python3 -m src.Experiments.legal_summarization.main \
  --dataset-source hub --streaming --mode extractive --limit 10
```

Run Exo-backed abstractive evaluation:

```bash
python -m src.Experiments.legal_summarization.main \
  --dataset-source hub --streaming --mode abstractive --limit 10
```

## Hugging Face authentication

Public datasets do not require a token. For gated/private datasets, place the
official variable in the repository `.env` file:

```dotenv
HF_TOKEN=hf_your_read_token
```

Or request hidden terminal input without persisting the token:

```bash
python3 -m src.Experiments.legal_summarization.main \
  --dataset-id owner/private-dataset \
  --prompt-for-hf-token --describe
```

The legacy `HUGGINGFACE_API_KEY` variable remains a compatibility fallback.
Tokens are never printed, written to the run database, or accepted as command
line values.

## Loading other datasets

Important options:

- `--dataset-id`: Hub repository.
- `--dataset-name`: named Hub subset/configuration.
- `--revision`: branch, tag, or commit SHA.
- `--data-file`: file/glob within the repository; repeat as needed.
- `--streaming`: iterate without downloading the complete dataset.
- `--input-column`, `--reference-column`, `--instruction-column`: schema map.
- `--task-column` and `--task-filter`: optional row filter. Pass
  `--task-filter ''` when the dataset has no task column.
- `--dataset-path`: local Parquet file or directory for offline runs.

For example, a dataset using `document` and `summary` columns can be inspected
with:

```bash
python -m src.Experiments.legal_summarization.main \
  --dataset-id owner/corpus --dataset-name default \
  --input-column document --reference-column summary \
  --task-filter '' --streaming --describe
```

## Outputs and metrics

Each successful source/reference pair records Unicode token-based ROUGE-1,
ROUGE-L, compression ratio, token counts, inference time, model mode, and the
generated/reference text. Aggregate metrics are stored on the run and included
in `logs/legal_summarization/run_<id>.md`.

These lightweight ROUGE-style scores use case-folded word tokens without
stemming, making the base pipeline work for English, Urdu, and Sindhi without
another model download. Use a specialized evaluator downstream when a
publication requires a particular tokenizer or canonical ROUGE package.
