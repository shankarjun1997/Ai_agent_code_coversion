# SQL Generation Agent POC (V1)

This POC runs a local Python pipeline:

1. Pull Jira story context
2. Fetch relevant BigQuery schema metadata
3. Ask an LLM to generate SQL + explanation
4. Validate with BigQuery dry run
5. Retry with error feedback if dry run fails

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Update `.env` with your credentials.

## Run

```bash
python main.py --issue-key DATA-1042 --max-retries 2
```

## Notes

- Uses `INFORMATION_SCHEMA.COLUMNS` and keyword filtering from Jira text.
- If no keyword match is found, it falls back to first 200 columns in dataset.
- V1 prints outputs in terminal only (no GitHub PR and no Jira comment write-back).
