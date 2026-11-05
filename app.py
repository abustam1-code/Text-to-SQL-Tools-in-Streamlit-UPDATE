import json
import re
from decimal import Decimal
from datetime import date, datetime
from typing import Any

import pandas as pd
import snowflake.connector
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Snowflake Text-to-SQL Agent", page_icon="❄️", layout="wide")

DATABASE = "SNOWFLAKE_SAMPLE_DATA"
SCHEMA = "TPCH_SF1"
ALLOWED_TABLES = {"CUSTOMER", "ORDERS", "LINEITEM", "SUPPLIER", "NATION", "REGION"}

st.title("❄️ Snowflake Text-to-SQL Agent")
st.caption("Powered by Gemini + Snowflake. Ask questions in plain English; the agent discovers metadata, writes read-only SQL, and runs it in Snowflake.")

# ---------- Configuration and connections ----------

def get_secret(name: str, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return default


def snowflake_connection():
    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
    missing = [key for key in required if not get_secret(key)]
    if missing:
        raise RuntimeError(
            "Missing Snowflake secrets: " + ", ".join(missing)
            + ". Add them in .streamlit/secrets.toml locally or in Streamlit Community Cloud settings."
        )

    return snowflake.connector.connect(
        account=get_secret("SNOWFLAKE_ACCOUNT"),
        user=get_secret("SNOWFLAKE_USER"),
        password=get_secret("SNOWFLAKE_PASSWORD"),
        warehouse=get_secret("SNOWFLAKE_WAREHOUSE", ""),
        role=get_secret("SNOWFLAKE_ROLE", None),
        database=DATABASE,
        schema=SCHEMA,
        login_timeout=30,
        network_timeout=60,
    )


def llm_client():
    """Use Gemini through Google's OpenAI-compatible API endpoint."""
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing GEMINI_API_KEY. Add it to Streamlit Community Cloud → Settings → Secrets."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


# ---------- The three agent tools ----------

def snowflake_table_lookup() -> dict:
    """List the six TPC-H tables this assignment uses."""
    return {
        "database": DATABASE,
        "schema": SCHEMA,
        "tables": sorted(ALLOWED_TABLES),
    }


def snowflake_column_lookup(table_name: str) -> dict:
    """Return column names and types for one approved table."""
    table = table_name.upper().strip()
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Table {table} is not in the approved TPC-H table list.")
    conn = snowflake_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT COLUMN_NAME, DATA_TYPE FROM {DATABASE}.INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            (SCHEMA, table),
        )
        rows = cur.fetchall()
        return {"table": table, "columns": [{"name": r[0], "type": r[1]} for r in rows]}
    finally:
        conn.close()


def is_read_only_select(sql: str) -> bool:
    cleaned = sql.strip()
    # Permit one SELECT or WITH...SELECT statement only.
    if not re.match(r"(?is)^(SELECT|WITH)\b", cleaned):
        return False
    # Reject multiple statements; permit one optional trailing semicolon.
    without_trailing = cleaned[:-1].rstrip() if cleaned.endswith(";") else cleaned
    if ";" in without_trailing:
        return False
    # Block common DDL/DML, session changes, and procedure execution.
    forbidden = r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|PUT|GET|COPY|REMOVE|CALL|EXECUTE|GRANT|REVOKE|USE|BEGIN|COMMIT|ROLLBACK)\b"
    if re.search(forbidden, without_trailing, flags=re.IGNORECASE):
        return False
    return True


def snowflake_execute_sql(sql: str) -> dict:
    """Execute one read-only SELECT query and return columns and rows."""
    if not is_read_only_select(sql):
        raise ValueError("Only one read-only SELECT/WITH query is allowed.")
    conn = snowflake_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(200) if columns else []
        def clean(value: Any):
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, Decimal):
                return float(value)
            return value
        data = [[clean(v) for v in row] for row in rows]
        return {
            "columns": columns,
            "rows": data,
            "row_count_returned": len(data),
            "truncated_at_200_rows": len(data) == 200,
        }
    finally:
        conn.close()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Snowflake_Table_Lookup",
            "description": "Step 1: discover the approved tables in the Snowflake TPC-H sample schema.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Snowflake_Table_Column_Lookup",
            "description": "Step 2: inspect the columns and data types of an approved table before writing SQL.",
            "parameters": {
                "type": "object",
                "properties": {"table_name": {"type": "string", "enum": sorted(ALLOWED_TABLES)}},
                "required": ["table_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Snowflake_Execute_SQL",
            "description": "Step 3: execute one read-only SELECT/WITH SQL statement in Snowflake. Never use for changes.",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "A single read-only Snowflake SELECT query."}},
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    },
]


def run_tool(name: str, arguments: dict) -> dict:
    if name == "Snowflake_Table_Lookup":
        return snowflake_table_lookup()
    if name == "Snowflake_Table_Column_Lookup":
        return snowflake_column_lookup(arguments["table_name"])
    if name == "Snowflake_Execute_SQL":
        return snowflake_execute_sql(arguments["sql"])
    raise ValueError(f"Unknown tool: {name}")


SYSTEM_PROMPT = f"""
You are a careful Snowflake Text-to-SQL assistant for a class assignment.
The only approved data source is {DATABASE}.{SCHEMA}. Use the three tools in order:
1) Snowflake_Table_Lookup to discover tables.
2) Snowflake_Table_Column_Lookup for the relevant table(s), before relying on column names.
3) Snowflake_Execute_SQL to run a single read-only query.

Use fully qualified table names: {DATABASE}.{SCHEMA}.TABLE.
Never invent table or column names. Never modify data or run DDL/DML.
When the query returns data, explain the result clearly and include the SQL used in a fenced sql code block.
For these assignment questions, use these relationships:
- CUSTOMER joins NATION on C_NATIONKEY = N_NATIONKEY.
- NATION joins REGION on N_REGIONKEY = R_REGIONKEY.
- ORDERS joins CUSTOMER on O_CUSTKEY = C_CUSTKEY.
- LINEITEM joins ORDERS on L_ORDERKEY = O_ORDERKEY when needed.
- SUPPLIER joins NATION on S_NATIONKEY = N_NATIONKEY.
Interpret "returned line items" as LINEITEM.L_RETURNFLAG = 'R'; sum L_QUANTITY.
Use AVG(C_ACCTBAL) grouped by C_MKTSEGMENT for customer average balances.
For nation total order price, sum ORDERS.O_TOTALPRICE by NATION.N_NAME through CUSTOMER and ORDERS.
For supplier balances by region, sum SUPPLIER.S_ACCTBAL grouped by REGION.R_NAME through NATION.
For order priority counts, count ORDERS rows grouped by O_ORDERPRIORITY.
If the user asks an unrelated question, still inspect metadata and answer only if the approved schema supports it.
If results are empty, say so; do not invent results.
"""


def ask_agent(question: str, prior_messages: list[dict]):
    client = llm_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + prior_messages + [
        {"role": "user", "content": question}
    ]
    visible_sql = []
    for _ in range(8):
        response = client.chat.completions.create(
            model=get_secret("GEMINI_MODEL", "gemini-2.5-flash"),
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0,
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            return msg.content or "I couldn't produce a response.", visible_sql, messages[1:]
        messages.append(msg)
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
                if call.function.name == "Snowflake_Execute_SQL":
                    visible_sql.append(args.get("sql", ""))
                result = run_tool(call.function.name, args)
                tool_content = json.dumps(result, default=str)
            except Exception as exc:
                tool_content = json.dumps({"error": str(exc)})
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": tool_content,
            })
    return "I reached the tool-call limit. Please try a narrower question.", visible_sql, messages[1:]


# ---------- Streamlit chat UI ----------

with st.sidebar:
    st.header("Connection status")
    st.write(f"**Database:** `{DATABASE}`")
    st.write(f"**Schema:** `{SCHEMA}`")
    st.caption("This app uses the Snowflake TPC-H sample dataset.")
    if st.button("Test Snowflake connection", use_container_width=True):
        try:
            conn = snowflake_connection()
            cur = conn.cursor()
            cur.execute("SELECT CURRENT_VERSION(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
            row = cur.fetchone()
            conn.close()
            st.success("Connected to Snowflake.")
            st.code(f"Version: {row[0]}\nRole: {row[1]}\nWarehouse: {row[2]}")
        except Exception as exc:
            st.error(str(exc))
    st.divider()
    st.markdown("**Agent tools**")
    st.markdown("1. `Snowflake_Table_Lookup`")
    st.markdown("2. `Snowflake_Table_Column_Lookup`")
    st.markdown("3. `Snowflake_Execute_SQL`")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.agent_messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []

suggestions = [
    "What is the average account balance for customers in each market segment?",
    "Which nation has the highest total order price?",
    "What is the total quantity of all line items that were returned?",
    "For each region, what is the total account balance of its suppliers?",
    "How many orders were placed for each order priority?",
]

if not st.session_state.messages:
    st.info("Try one of the five assignment questions below, or type your own question.")
    cols = st.columns(2)
    for i, prompt in enumerate(suggestions):
        if cols[i % 2].button(prompt, key=f"suggestion_{i}", use_container_width=True):
            st.session_state.pending_question = prompt
            st.rerun()

for item in st.session_state.messages:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])
        if item.get("sql"):
            with st.expander("View generated SQL"):
                for statement in item["sql"]:
                    st.code(statement, language="sql")
        if item.get("data") is not None:
            st.dataframe(pd.DataFrame(item["data"]["rows"], columns=item["data"]["columns"]), use_container_width=True)

question = st.chat_input("Ask a question about the Snowflake data...")
if st.session_state.get("pending_question"):
    question = st.session_state.pop("pending_question")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Looking up schema, generating SQL, and querying Snowflake..."):
                answer, sql_statements, agent_history = ask_agent(
                    question,
                    st.session_state.agent_messages,
                )
            st.markdown(answer)
            if sql_statements:
                with st.expander("View generated SQL", expanded=True):
                    for statement in sql_statements:
                        st.code(statement, language="sql")
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "sql": sql_statements,
            })
            st.session_state.agent_messages = agent_history
        except Exception as exc:
            error = f"**The agent could not complete the request.**\n\n{exc}"
            st.error(error)
            st.session_state.messages.append({"role": "assistant", "content": error})
