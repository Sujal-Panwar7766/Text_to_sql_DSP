# AI Text to SQL

A Streamlit app that lets you upload CSV files, store them in MySQL, and explore them with AI-generated SQL.

## Features

- Upload one or more CSV files into MySQL
- Ask natural-language questions about one or many uploaded tables
- AI-generated example questions based on the uploaded schema
- Editable SQL before execution
- Query history with reuse support
- AI result summaries and follow-up questions
- Smart chart suggestions for result sets
- CSV and Excel downloads
- Upload-time data insights
- Lightweight dashboard mode for saved query results

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Install and start a MySQL server locally.

`MySQL Workbench` is only a GUI client, not the MySQL server itself. If you want to stop using XAMPP, install standalone `MySQL Server`, then use Workbench to manage that server.

3. Add your Groq API key and DB settings to `.env`:

```env
GROQ_API_KEY=your_key_here
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=mydb
DB_CONNECTION_TIMEOUT=5
```

4. Start the app:

```bash
streamlit run app.py
```

## Notes

- Only `SELECT` queries are allowed from the editable SQL runner.
- Multi-table questions work best when uploaded tables share clearly named columns.

## Free Deployment

The easiest free deployment for this project is:

- `Streamlit Community Cloud` for the app
- `Aiven MySQL Free Tier` for the database

### 1. Create a free MySQL database

Create a MySQL service on Aiven, then copy:

- `host`
- `port`
- `database`
- `username`
- `password`

If Aiven provides a CA certificate, keep that too.

### 2. Add app secrets

For local Streamlit secrets, copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml` and fill it in.

For Streamlit Community Cloud, paste the same values into your app's `Advanced settings -> Secrets` box.

Example:

```toml
GROQ_API_KEY = "your_groq_api_key"

DB_HOST = "your-db-host"
DB_PORT = "3306"
DB_USER = "your-db-user"
DB_PASSWORD = "your-db-password"
DB_NAME = "mydb"
DB_CONNECTION_TIMEOUT = "5"

DB_SSL_VERIFY_CERT = "true"
DB_SSL_CA = """
-----BEGIN CERTIFICATE-----
paste-your-ca-certificate-here
-----END CERTIFICATE-----
"""
```

`DB_SSL_CA` can be either:

- a filesystem path to the CA certificate, or
- the full PEM certificate text

### 3. Deploy the app

In Streamlit Community Cloud:

1. Sign in with GitHub.
2. Click `Create app`.
3. Select this repository.
4. Set the entrypoint to `app.py`.
5. In `Advanced settings`, set Python to `3.12`.
6. Paste your secrets.
7. Click `Deploy`.

### 4. Important note

Streamlit Community Cloud free apps are public, so anyone with the URL can open the app.
