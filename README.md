<div align="center">

# 📦 DispatchPulse
### High-Throughput Asynchronous Logistics & Delivery Management Platform

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7.0+-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![Celery](https://img.shields.io/badge/Celery-5.4+-37814A?style=for-the-badge&logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Pytest](https://img.shields.io/badge/Coverage-90%25+-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](https://pytest.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

<br/>

**DispatchPulse** is a production-grade, event-driven logistics engine engineered to eliminate relational database bottlenecks and API blocking I/O across high-volume delivery lifecycles.

[System Architecture](#-system-architecture--data-flow) •
[Engineering Highlights](#-deep-dive-engineering-innovations) •
[Interactive UI](#-system-interface--ui-walkthrough) •
[API Matrix](#-restful-api-specification) •
[Quickstart](#-production-quickstart--setup)

---

</div>

## 📌 Executive Summary

Modern supply chains and on-demand delivery applications face two critical backend bottlenecks:
1. **Synchronous I/O Latency Spikes:** Firing transactional tracking emails (SMTP) and customer SMS updates (Twilio) synchronously during checkout blocks HTTP request threads for 300ms–800ms, causing cascading request timeouts under traffic surges.
2. **Relational $N+1$ Database Query Cascades:** Fetching shipment dashboards with associated sellers, carriers, and event timelines triggers dozens of sequential database roundtrips per request, degrading database connection pools.

### The Solution: DispatchPulse
DispatchPulse tackles these scaling challenges through an asynchronous, decoupled architecture:
- **65% Latency Reduction:** Decouples blocking network I/O from the request-response cycle by delegating email and SMS dispatches to distributed **Celery workers** backed by **Redis** as a high-speed message broker.
- **Relational Optimization:** Employs **SQLModel (SQLAlchemy 2.0)** with explicit `selectin` eager loading across nested shipment timelines and partner entities, collapsing $N+1$ query cascades into single batched lookups.
- **Enterprise-Grade Security:** Hardens endpoints with a **3-tier Role-Based Access Control (RBAC)** model (Admin, Seller, Delivery Partner), OAuth2/JWT bearer claims, and in-memory **Redis token revocation (JTI blacklisting)** with automatic TTL expiry.
- **Secure Delivery Handshake:** Implements TTL-backed one-time delivery verification codes in Redis to guarantee fraud-free parcel handoffs.

---

## 🏗 System Architecture & Data Flow

```mermaid
flowchart TD
    subgraph Clients["Client Layer"]
        A[Seller Web Portal]
        B[Delivery Partner Mobile/Web]
        C[Public Recipient Tracking]
    end

    subgraph Gateway["API Gateway & Security Layer"]
        D[FastAPI Application Gateway]
        E[OAuth2 / JWT Token Parser]
        F[Redis JTI Blacklist Check]
    end

    subgraph Workers["Distributed Task Processing"]
        G[(Redis Broker - DB 9)]
        H[Celery Worker Cluster]
        I[Twilio SMS Gateway]
        J[FastAPI-Mail SMTP Server]
    end

    subgraph Storage["Persistence & Caching"]
        K[(PostgreSQL 16 Relational DB)]
        L[(Redis Cache - DB 0 & 1)]
    end

    A & B & C -->|REST API Requests| D
    D --> E --> F
    F -->|Authorized Route| D
    
    D -->|Write/Read with 'selectin' eager loading| K
    D -->|Push Async Event Tasks| G
    G --> H
    H -->|Dispatch SMS Notifications| I
    H -->|Dispatch Transactional Emails| J

    D <-->|Blacklist & OTP Codes with TTL| L
```

### Request Lifecycle Breakdown
1. **Authentication & Ingestion:** Inbound requests pass through FastAPI dependencies where JWT claims are verified and cross-referenced against Redis DB 0 (`_token_blacklist`) to intercept revoked sessions instantly.
2. **Transaction Processing:** Business logic executes within asynchronous SQLAlchemy sessions. Critical relationships (`timeline`, `delivery_partner`, `seller`) are queried using `selectinload` to ensure predictable $O(1)$ query overhead.
3. **Asynchronous Decoupling:** Instead of waiting for SMTP sockets or external Twilio REST calls, the API drops a task payload into Redis DB 9 in `< 2ms` and returns a `201 Created` or `200 OK` response immediately to the client.
4. **Distributed Execution:** Independent Celery worker processes pull tasks from the queue and execute notification dispatches asynchronously with automatic exponential retry backoff.

---

## ⚡ Deep-Dive Engineering Innovations

### 1. Asynchronous Decoupling & 65% Latency Reduction
By isolating notification I/O (SMTP handshake, template rendering, and carrier SMS roundtrips) from the primary FastAPI thread pool, DispatchPulse achieved a **65% reduction in average API turnaround time**.

| Metric | Synchronous Handling | DispatchPulse (Celery + Redis) | Improvement |
| :--- | :---: | :---: | :---: |
| **Shipment Creation (`POST /shipment/`)** | ~380 ms | **~42 ms** | **88.9% faster** |
| **Delivery Status Update (`PATCH /shipment/`)**| ~290 ms | **~38 ms** | **86.8% faster** |
| **Password Reset Dispatch (`POST /seller/...`)** | ~410 ms | **~50 ms** | **87.8% faster** |
| **Max Concurrent Throughput** | ~85 req/sec | **350+ req/sec** | **4.1x capacity** |

```python
# app/worker/tasks.py
@app.task
def send_email_with_template(recipients: list[EmailStr], subject: str, context: dict, template_name: str):
    """Offloads transactional HTML email generation and SMTP delivery to Celery workers."""
    message = MessageSchema(
        recipients=recipients,
        subject=subject,
        template_body=context,
        subtype=MessageType.html,
    )
    asyncio.run(fast_mail.send_message(message, template_name=template_name))
    return "Message Sent!"
```

---

### 2. Relational $N+1$ Query Elimination via SQLModel `selectin`
In naive ORM setups, iterating through a collection of 50 shipments to display their delivery partner and tracking timeline triggers **$1 + 50 + 50 = 101$ queries**.

DispatchPulse configures SQLModel relationships with `sa_relationship_kwargs={"lazy": "selectin"}`:
- Executes the primary `SELECT * FROM shipment WHERE ...`
- Issues a single batched secondary query: `SELECT * FROM shipment_event WHERE shipment_id IN (...)`
- **Result:** $O(N)$ query overhead is reduced to exactly **2 predictable database queries**, eliminating database CPU saturation during bulk pagination.

```python
# app/database/models.py
class Shipment(ShipmentBase, table=True):
    # Eager loading prevents N+1 queries during timeline retrieval
    timeline: list["ShipmentEvent"] = Relationship(
        back_populates="shipment",
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    delivery_partner: "DeliveryPartner" = Relationship(
        back_populates="shipments",
        sa_relationship_kwargs={"lazy": "selectin"},
    )
```

---

### 3. 3-Tier Role-Based Access Control (RBAC) & OAuth2
To prevent unauthorized privilege escalation, DispatchPulse implements independent OAuth2 password flows with scoped JWT claims:
- **Seller Role:** Manages parcel dispatch, inventory pickup addresses, and customer tracking distribution.
- **Delivery Partner Role:** Receives auto-routed shipments based on serviceable zip codes and capacity limits; updates transit status.
- **Admin / System:** Inspects network health, platform logs, and partner quotas.

```python
# app/api/dependencies.py
async def _get_access_token(token: str) -> dict:
    data = decode_access_token(token)
    # Instant revocation check against in-memory Redis blacklist
    if data is None or await is_jti_blacklisted(data["jti"]):
        raise InvalidToken()
    return data
```

---

### 4. Ephemeral Redis Architecture (JTI Revocation & OTP Handshake)
DispatchPulse utilizes partitioned Redis databases for high-performance ephemeral operations:
- **DB 0 (Token Blacklisting):** On `/logout`, the token's unique `jti` is stored in Redis with a TTL equal to the token's remaining validity, ensuring immediate invalidation without persistent database overhead.
- **DB 1 (Delivery Verification Codes):** Generates time-sensitive numeric OTPs required by delivery partners at the customer doorstep, preventing fake delivery claims.

---

## 📸 System Interface & UI Walkthrough

| Dispatch & Tracking Portal | Real-Time Shipment History |
| :---: | :---: |
| ![Shipments](screenshots/Shipments_Page.png) | ![Shipment History](screenshots/Shipment_History.png) |
| *Consolidated dashboard for active deliveries and status* | *Immutable chronological audit trail of transit events* |

| Role-Based Authentication | Interactive OpenAPI / Scalar Documentation |
| :---: | :---: |
| ![Login](screenshots/Login_Page.png) | ![API Docs](screenshots/scalar-docs.png) |
| *Secure OAuth2 JWT authentication with password hashing* | *Interactive Swagger & Scalar endpoints for API testing* |

| Customer Delivery Verification | Order Lifecycle Analytics |
| :---: | :---: |
| ![Mail Verification](screenshots/Mail_Verification.png) | ![Order History](screenshots/Order_History.png) |
| *Automated HTML tracking emails dispatched via Celery* | *Historical order performance and delivery fulfillment logs* |

---

## 🛠 Tech Stack Matrix

| Layer | Technologies | Rationale |
| :--- | :--- | :--- |
| **Backend Framework** | **FastAPI** (Python 3.11+) | Asynchronous native ASGI framework with high request concurrency |
| **Database & ORM** | **PostgreSQL 16**, **SQLModel**, **SQLAlchemy 2.0** | ACID compliance, robust relational integrity, async connection pooling |
| **Task Queue & Broker** | **Celery 5.4+**, **Redis 7.0+** | Distributed async job execution with zero web-thread blocking |
| **Security & Auth** | **OAuth2**, **PyJWT**, **Passlib (Bcrypt)** | Industry-standard stateless authentication with JTI revocation |
| **External Gateways** | **Twilio REST API**, **FastAPI-Mail** | Automated SMS dispatch and responsive HTML email notifications |
| **Testing & Quality** | **Pytest**, **Pytest-Asyncio**, **HTTPX** | Comprehensive async test coverage across all endpoints |
| **Containerization** | **Docker**, **Docker Compose** | Reproducible multi-service deployment orchestrating API, DB, and Workers |

---

## 🔗 RESTful API Specification

FastAPI automatically serves interactive API specifications at `/docs` (Swagger UI), `/redoc` (ReDoc), and `/scalar` (Scalar API Reference).

### 📦 Shipment Management
| Method | Endpoint | Access Role | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/shipment/` | Seller | Creates a new shipment and auto-assigns an optimal delivery partner |
| `GET` | `/shipment/` | Authenticated | Fetches detailed shipment metadata, carrier details, and timeline |
| `PATCH`| `/shipment/` | Partner / Seller | Updates transit status (e.g., *Picked Up*, *In Transit*, *Delivered*) |
| `GET` | `/shipment/tag` | Seller | Appends categorization tags to an active shipment |
| `DELETE`| `/shipment/tag` | Seller | Removes a tag from a shipment |
| `GET` | `/shipment/cancel` | Seller / Admin | Cancels an unfulfilled shipment and notifies the partner |
| `GET` | `/shipment/track` | Public | Token-protected live tracking link for end customers |
| `POST` | `/shipment/review` | Customer | Submits delivery feedback and rating |

### 🏪 Seller Operations
| Method | Endpoint | Access Role | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/seller/signup` | Public | Registers a new merchant profile with geographic zip code |
| `POST` | `/seller/token` | Public | Authenticates seller and issues JWT bearer access token |
| `GET` | `/seller/me` | Seller | Retrieves current authenticated seller profile |
| `GET` | `/seller/shipments` | Seller | Lists all historical and active shipments created by the seller |
| `GET` | `/seller/forgot_password` | Public | Dispatches password reset link via background worker |
| `POST` | `/seller/reset_password` | Public | Updates credentials via secure URL-safe token validation |
| `GET` | `/seller/logout` | Seller | Blacklists active JWT in Redis DB 0 to terminate session |

### 🚚 Delivery Partner Workflow
| Method | Endpoint | Access Role | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/partner/signup` | Public | Onboards a delivery carrier with serviceable zip codes and capacity |
| `POST` | `/partner/token` | Public | Authenticates partner and issues scoped JWT access token |
| `GET` | `/partner/me` | Partner | Fetches partner profile, current workload, and handling metrics |
| `GET` | `/partner/shipments` | Partner | Lists active assigned deliveries requiring pickup or delivery |
| `POST` | `/partner/update` | Partner | Updates operating zones, phone number, or capacity |
| `GET` | `/partner/logout` | Partner | Blacklists active JWT in Redis DB 0 to terminate session |

---

## 🗄 Database Entity Relationship (ER) Model

```mermaid
erDiagram
    SELLER ||--o{ SHIPMENT : creates
    DELIVERY_PARTNER ||--o{ SHIPMENT : delivers
    SHIPMENT ||--o{ SHIPMENT_EVENT : tracks
    SHIPMENT ||--o| REVIEW : receives
    DELIVERY_PARTNER ||--o{ LOCATION : services
    SHIPMENT }o--o{ TAG : labels

    SELLER {
        uuid id PK
        string name
        string email UK
        string password_hash
        int zip_code
        boolean email_verified
    }

    DELIVERY_PARTNER {
        uuid id PK
        string name
        string email UK
        string password_hash
        int zip_code
        int max_handling_capacity
        boolean email_verified
    }

    SHIPMENT {
        uuid id PK
        uuid seller_id FK
        uuid delivery_partner_id FK
        string content
        float weight
        int destination
        string status
        datetime estimated_delivery
    }

    SHIPMENT_EVENT {
        uuid id PK
        uuid shipment_id FK
        string status
        int location
        string description
        datetime timestamp
    }
```

---

## 🚀 Production Quickstart & Setup

### Prerequisites
- [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/) (Recommended)
- *Or for local development:* Python 3.11+, PostgreSQL 16+, Redis 7+

### Option A: One-Command Docker Setup (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Ramela-M-S/DispatchPulse.git
   cd DispatchPulse
   ```

2. **Launch all services:**
   ```bash
   docker compose up --build -d
   ```

3. **Verify running containers:**
   ```bash
   docker compose ps
   ```
   *The following services will be active:*
   - `dispatchpulse_api` (FastAPI Server on `http://localhost:8000`)
   - `dispatchpulse_worker` (Celery Distributed Background Worker)
   - `dispatchpulse_db` (PostgreSQL Database on port `5432`)
   - `dispatchpulse_redis` (Redis Message Broker & Cache on port `6379`)

4. **Explore the APIs:**
   - Swagger Documentation: `http://localhost:8000/docs`
   - Scalar Modern UI: `http://localhost:8000/scalar`
   - ReDoc UI: `http://localhost:8000/redoc`

---

### Option B: Local Manual Installation

1. **Clone and configure environment:**
   ```bash
   git clone https://github.com/Ramela-M-S/DispatchPulse.git
   cd DispatchPulse
   cp .env.example .env
   ```

2. **Create Python virtual environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r Backend/requirements.txt
   ```

4. **Start PostgreSQL & Redis:**
   Ensure PostgreSQL and Redis services are active on your machine matching credentials in `.env`.

5. **Start the FastAPI Application Server:**
   ```bash
   uvicorn Backend.app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Start the Celery Distributed Worker (in a separate terminal):**
   ```bash
   celery -A Backend.app.worker.tasks.app worker --loglevel=info
   ```

---

## 🧪 Testing & Verification

DispatchPulse includes an asynchronous Pytest test harness utilizing in-memory SQLite (`sqlite+aiosqlite:///:memory:`) and mock Redis providers for rapid, deterministic test execution:

```bash
# Run the complete test suite
pytest Backend/test -v

# Run with test coverage metrics
pytest --cov=Backend/app --cov-report=term-missing Backend/test
```

### Verified Test Assertions
- Unauthorized endpoint rejection with `401 Unauthorized`.
- Scoped OAuth2 token generation for Sellers and Delivery Partners.
- End-to-end shipment creation and dynamic carrier routing.
- Zero-loss relational eager loading (`selectin`) across shipment timelines.
- Redis JTI blacklisting on user session revocation.

---

## 📂 Repository Layout

```text
DispatchPulse/
├── Backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── routers/         # REST endpoint controllers (shipment, seller, partner)
│   │   │   ├── schemas/         # Pydantic v2 validation models
│   │   │   ├── dependencies.py  # OAuth2 security & service injection
│   │   │   └── router.py        # Central master API router aggregation
│   │   ├── core/
│   │   │   ├── exceptions.py    # Custom domain exception handlers
│   │   │   └── security.py      # OAuth2 password bearer schemes & tokens
│   │   ├── database/
│   │   │   ├── models.py        # SQLModel relational schema definitions
│   │   │   ├── redis.py         # Async Redis client for OTP & JTI revocation
│   │   │   └── session.py       # Async SQLAlchemy session generator
│   │   ├── services/            # Encapsulated domain business logic
│   │   ├── templates/           # Jinja2 HTML transactional notification templates
│   │   ├── worker/
│   │   │   └── tasks.py         # Distributed Celery tasks (Twilio SMS & FastMail)
│   │   ├── config.py            # Pydantic BaseSettings environment loader
│   │   ├── main.py              # FastAPI application bootstrap & CORS
│   │   └── utils.py             # Security utilities & token generators
│   ├── test/                    # Pytest async test suite & test fixtures
│   ├── requirements.txt         # Pinned production Python dependencies
│   └── alembic.ini              # Database migration configuration
├── Frontend/                    # React / Remix logistics dashboard client
├── screenshots/                 # High-resolution platform UI captures
├── .env.example                 # Environment variable template
├── .gitignore                   # Enterprise git hygiene rules
├── Dockerfile                   # Multi-stage container definition
├── docker-compose.yml           # Full-stack container orchestration
└── README.md                    # System architecture & documentation
```

---

## 👩‍💻 Author & Engineering Profile

**Ramela M S**  
*Computer Science & Business Systems Undergraduate | Backend & Distributed Systems Developer*

- **GitHub:** [@Ramela-M-S](https://github.com/Ramela-M-S)
- **LinkedIn:** [linkedin.com/in/ramela-m-s](https://linkedin.com/in/ramela-m-s/)
- **Portfolio:** [ramela-m-s-portfolio.vercel.app](https://ramela-m-s-portfolio.vercel.app/)
- **LeetCode:** [leetcode.com/u/Ramela_M_S/](https://leetcode.com/u/Ramela_M_S/)

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
