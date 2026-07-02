# Stage 1 — build the SPA
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Production builds talk to the real backend, never the mocks
ENV VITE_USE_MOCKS=false
RUN npm run build

# Stage 2 — serve static files + proxy /api to the backend
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
