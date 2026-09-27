FROM node:22-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
ARG KICHU_NPM_REGISTRY=https://registry.npmjs.org/
RUN npm ci --registry="${KICHU_NPM_REGISTRY}" --replace-registry-host=always

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

RUN addgroup -S -g 10001 app && \
    adduser -S -D -H -u 10001 -G app app && \
    mkdir -p /var/cache/nginx /var/run && \
    touch /var/run/nginx.pid && \
    chown -R app:app /var/cache/nginx && \
    chown app:app /var/run/nginx.pid

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

USER app
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
