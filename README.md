# Snowflake Text-to-SQL Agent

A Streamlit chat app that uses an OpenAI model and three tools to inspect and query Snowflake's `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1` sample schema.

## Included agent tools

1. `Snowflake_Table_Lookup` — lists the approved TPC-H tables.
2. `Snowflake_Table_Column_Lookup` — inspects columns and data types.
3. `Snowflake_Execute_SQL` — runs one read-only SELECT/WITH statement.

## 1. Requirements

- Python 3.10+
- A Snowflake account with access to `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1`
- An OpenAI API key

## 2. Configure secrets

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your credentials.

For `SNOWFLAKE_ACCOUNT`, use the account identifier shown in your Snowflake account details. Do not include `https://` or `.snowflakecomputing.com`.

Never commit `.streamlit/secrets.toml` to GitHub. The `.gitignore` file excludes it.

## 3. Install and run locally

```bash
python -m venv .venv
```

Windows PowerShell:
```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:
```bash
source .venv/bin/activate
```

Then:
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 4. Deploy on Streamlit Community Cloud

1. Push this project to a GitHub repository.
2. In Streamlit Community Cloud, create an app from that repository and select `app.py`.
3. Open the app's **Settings → Secrets**.
4. Paste the contents of your configured `secrets.toml` (with your real values).
5. Save and reboot the app.

Do not put credentials in GitHub, source code, screenshots, or README files.

## 5. Assignment questions

- What is the average account balance for customers in each market segment?
- Which nation has the highest total order price?
- What is the total quantity of all line items that were returned?
- For each region, what is the total account balance of its suppliers?
- How many orders were placed for each order priority?

## Notes

- The app is configured for Snowflake's TPC-H `TPCH_SF1` sample schema.
- If your course uses a different database/schema, update `DATABASE` and `SCHEMA` in `app.py`, and adjust the approved table names and system prompt accordingly.
- Snowflake access depends on your account role and warehouse privileges.
- SQL execution is restricted to a single read-only SELECT/WITH statement. Review generated SQL before using it for anything beyond this assignment.
