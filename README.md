# MedQ

Private AMC + FMGE practice platform for two users.

## Phase 1 included
- Landing page
- Supabase email/password authentication
- Separate per-user dashboard
- Database schema with RLS
- FastAPI backend skeleton
- Tables ready for books, questions, attempts and bookmarks

## Folder structure
```text
medq-starter/
├─ frontend/
├─ backend/
├─ supabase/
│  └─ schema.sql
├─ .gitignore
└─ README.md
```

## 1. Create Supabase project
Create a free Supabase project.

Open:
SQL Editor -> New query

Paste all contents of:
`supabase/schema.sql`

Run it.

## 2. Configure frontend
Copy:
`frontend/.env.example`
to:
`frontend/.env.local`

Fill:
```env
VITE_SUPABASE_URL=...
VITE_SUPABASE_PUBLISHABLE_KEY=...
VITE_API_URL=http://localhost:8000
```

Get URL and Publishable Key from Supabase Project -> Connect/API settings.

## 3. Run frontend locally
```bash
cd frontend
npm install
npm run dev
```

## 4. Run backend locally
```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

## 5. Create the two users
Use the website's Create Account mode for each email.
Or create users inside Supabase Authentication.

To make one account the admin:
Supabase -> SQL Editor:
```sql
update public.profiles
set role = 'admin'
where id = (
  select id from auth.users where email = 'YOUR_ADMIN_EMAIL'
);
```

## 6. GitHub
Create one repository called:
`medq`

Upload the contents of this folder to the repository root.

## Next phase
- Library page
- Cloudflare R2 direct PDF upload
- Admin-only upload controls
- Book processing status
- Local OCR worker
