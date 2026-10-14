# ApexRx-Smart

ApexRx-Smart is a medicine availability platform designed to help patients, healthcare professionals, pharmacies, and suppliers access information about medicine availability.

## Project Structure

```text
apexrx-smart/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   └── schemas/
│   ├── alembic/
│   ├── requirements.txt
│   └── alembic.ini
├── database/
│   └── db_implementation_script.sql
└── frontend/
```

## Backend Setup

### Prerequisites

- Python compatible with the installed dependencies
- PostgreSQL
- Git

### 1. Create the database

Create a PostgreSQL database for ApexRx-Smart.

The initial database schema is defined in `database/db_implementation_script.sql`. Execute this script against the newly created database to create the initial tables.

### 2. Configure environment variables

Create a `.env` file inside the `backend/` directory with the following variables:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE
JWT_SECRET_KEY=replace-with-a-strong-random-secret
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Replace the database connection placeholders with your own PostgreSQL credentials and database name. Generate a strong, unique secret for JWT signing.

**Security:** Never commit `.env` files, database credentials, or JWT secrets to Git.

### 3. Install dependencies

From the repository root:

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment.

On Git Bash for Windows:

```bash
source .venv/Scripts/activate
```

On Linux or macOS:

```bash
source .venv/bin/activate
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

### 4. Initialize the migration history

The current baseline migration assumes that the original database schema already exists. It does not create the initial tables.

For a **new database** initialized using `database/db_implementation_script.sql`, run the following from the `backend/` directory after configuring `.env`:

```bash
alembic stamp 5c11125c47b6
alembic upgrade head
```

The first command records the existing initial schema as the baseline. The second applies subsequent migrations, including the addition of the `password_hash` column.

For an existing database that is already at the latest migration revision, do not stamp the baseline again. Check its state first:

```bash
alembic current
alembic heads
```

### 5. Start the API

From the `backend/` directory, with the virtual environment activated:

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at:

- API base URL: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Checks API and database connectivity |
| GET | `/medicines/availability` | Retrieves available, unexpired medicine stock |
| POST | `/auth/register` | Registers a user account |
| POST | `/auth/login` | Authenticates a user and returns a bearer token |

See `/docs` for request schemas, parameters, and response formats.

## Frontend Integration

The backend currently permits browser requests from these local development origins:

- `http://127.0.0.1:5501`
- `http://localhost:5501`

If the frontend is served from a different origin, update the backend CORS configuration accordingly.

## Database Migrations

Alembic manages schema changes after the initial database schema has been created.

Check the current revision:

```bash
alembic current
```

Inspect the migration history:

```bash
alembic history
```

Check for differences between SQLAlchemy models and the database:

```bash
alembic check
```

Review generated migration scripts before applying them. Test migrations against a separate development database before using them on a database containing important data.
