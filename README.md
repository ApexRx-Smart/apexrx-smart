# ApexRx-Smart

ApexRx-Smart is a medicine availability platform designed to help patients, healthcare professionals, pharmacies, and suppliers access information about medicine availability.

The project includes a static frontend, a FastAPI backend, and a PostgreSQL database schema. The frontend currently contains a pharmacy workflow demonstration, while the backend provides the initial API and database foundation.

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
├── frontend/
│   ├── assets/
│   │   ├── images/
│   │   └── logos/
│   ├── css/
│   ├── js/
│   ├── index.html
│   └── pharmacies.html
├── PHARMACY-WORKFLOW.md
└── README.md
```

## Frontend

The frontend is a static website and pharmacy workflow demonstration. No frontend build step is required.

### Run locally

From the repository root, run:

```bash
python -m http.server 5501 --directory frontend
```

Open the following pages in your browser:

- Home page: http://localhost:5501/
- Pharmacy workflow: http://localhost:5501/pharmacies.html

Stop the server with `Ctrl+C`.

### Static hosting

For static hosting, set the published directory to `frontend/`. No build step is required.

If the entire repository is served instead, open `/frontend/`.

### Verify frontend changes

After making changes, check the following:

1. Open the home page and verify the Kigali map, logos, audience images, and animations.
2. Select English, French, and Kinyarwanda and verify that the language selection is applied.
3. Open the pharmacy workflow and follow the demonstration signup process using a sample email, matching test passwords, and the demonstration verification code `472916`.
4. Continue through the profile and simulated payment steps, then check supplier search and demonstration chat.
5. Check narrow and wide layouts, navigation, return navigation, and social links.

### Frontend demonstration limitations

The pharmacy workflow is a frontend demonstration. Account creation, document uploads, payments, and supplier messaging should not be assumed to perform real transactions unless their backend integrations have been implemented.

External Google Fonts and the existing YouTube background require network access and remain subject to browser and provider restrictions.

See [PHARMACY-WORKFLOW.md](PHARMACY-WORKFLOW.md) for additional workflow details and demonstration limitations.

## Backend

The backend uses FastAPI, SQLAlchemy, PostgreSQL, and Alembic. It provides the initial API foundation for medicine availability and future pharmacy inventory management.

### Prerequisites

- Python compatible with the installed dependencies
- PostgreSQL
- Git

### 1. Create the database

Create a PostgreSQL database for ApexRx-Smart.

The initial database schema is defined in `database/db_implementation_script.sql`. Execute this script against the newly created database to create the initial tables.

The baseline Alembic migration does not create the initial tables. The schema must exist before the baseline revision is stamped.

### 2. Configure environment variables

Create a `.env` file inside the `backend/` directory with the following variables:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE
JWT_SECRET_KEY=replace-with-a-strong-random-secret
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Replace the database connection placeholders with your PostgreSQL credentials and database name. Generate a strong, unique secret for JWT signing.

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

For a **new database** initialized using `database/db_implementation_script.sql`, run the following commands from the `backend/` directory after configuring `.env`:

```bash
alembic stamp 5c11125c47b6
alembic upgrade head
```

The first command records the existing initial schema as the baseline. The second applies subsequent migrations, including the addition of the `password_hash` column.

For an existing database, inspect its migration state first:

```bash
alembic current
alembic heads
```

Do not stamp the baseline again if the database is already tracked at the appropriate revision. Do not run initialization commands against a database containing important data without first verifying its state and taking an appropriate backup.

### 5. Start the API

From the `backend/` directory, with the virtual environment activated:

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at:

- API base URL: http://127.0.0.1:8000
- Interactive API documentation: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Checks API and database connectivity |
| GET | `/medicines/availability` | Retrieves available, unexpired medicine stock |
| POST | `/auth/register` | Registers a user account |
| POST | `/auth/login` | Authenticates a user and returns a bearer token |

See `/docs` for request schemas, parameters, and response formats.

### Authentication status

Registration and login use password hashing, and login issues a JWT access token. JWT verification on subsequent requests and authorization for protected pharmacy-management endpoints remain future work.

The medicine availability endpoint is currently publicly accessible. The current authentication implementation should not be treated as a complete authorization system.

## Frontend and Backend Integration

Run the frontend and backend in separate terminals during local development.

The backend currently permits browser requests from these origins:

- `http://127.0.0.1:5501`
- `http://localhost:5501`

The frontend can retrieve medicine availability from:

```text
GET http://127.0.0.1:8000/medicines/availability
```

If the frontend is served from a different origin, update the backend CORS configuration accordingly.

The medicine availability endpoint returns information from the configured database. Demonstration records are not evidence of live availability at real pharmacies.

## Database Models

The initial database schema covers:

- Users
- Organizations
- Memberships
- Locations
- Drugs
- Products
- Batches
- Stock

The schema is defined in `database/db_implementation_script.sql`, while SQLAlchemy models are maintained under `backend/app/models/`.

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

## Development Roadmap

Planned backend work includes:

- JWT verification and protected endpoints.
- Role-based authorization for pharmacy and organizational workflows.
- Pharmacy inventory-management endpoints.
- Integration of authentication and inventory workflows with the frontend.
- Automated backend tests.

The frontend and backend should be developed and tested independently before their integration is treated as production-ready.
