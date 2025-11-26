# Dashboard (React + Vite)

## Env

Create `.env` in this folder:
```
VITE_API_BASE_URL=http://monimoni-api-vz7ufo-7d93fb-45-87-120-125.traefik.me
VITE_API_TOKEN=cu1F9hE3pKq7sZb4nVw2Yt6uRj8mLx9d
```

## Geliştirme
```
npm install
npm run dev -- --host --port 5173
```

## Build / Deploy
```
npm install
npm run build
npm run preview -- --host 0.0.0.0 --port 4173
```

Dokploy için:
- Build Type: Dockerfile (yoksa buildpacks) veya Node build komutları `npm install && npm run build`.
- Start command: `npm run preview -- --host 0.0.0.0 --port 4173`
- Env: VITE_API_BASE_URL, VITE_API_TOKEN
- Expose: 4173
