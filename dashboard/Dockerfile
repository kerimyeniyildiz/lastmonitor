FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# Use npx to avoid execute-bit issues on local bin
RUN npx vite build

FROM node:20-alpine AS runner
WORKDIR /app
RUN npm install -g serve
COPY --from=builder /app/dist ./dist

ENV PORT=4173
EXPOSE 4173
CMD ["serve", "-s", "dist", "-l", "4173", "-n"]
