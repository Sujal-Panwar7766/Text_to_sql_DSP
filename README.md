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

3. Add your Groq API key to `.env`:

```env
GROQ_API_KEY=your_key_here
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=mydb
```

4. Start the app:

```bash
streamlit run app.py
```

## Notes

- Only `SELECT` queries are allowed from the editable SQL runner.
- Multi-table questions work best when uploaded tables share clearly named columns.
