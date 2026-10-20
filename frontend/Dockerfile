FROM node:22-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
ARG KICHU_NPM_REGISTRY=https://registry.npmjs.org/
RUN npm ci --registry="${KICHU_NPM_REGISTRY}" --replace-registry-host=always

COPY . .
RUN npm run build

FROM builder AS runtime-deps
RUN npm prune --omit=dev

FROM node:22-alpine AS public-pages
WORKDIR /app
RUN addgroup -S -g 10001 app && adduser -S -D -H -u 10001 -G app app && mkdir /cache && chown app:app /cache
COPY --from=runtime-deps /app/node_modules ./node_modules
COPY --from=builder /app/dist-server ./dist-server
COPY package.json ./
COPY public-pages ./public-pages
COPY src/routing/publicRoutes.js ./src/routing/publicRoutes.js
COPY src/publicPages/contract.js ./src/publicPages/contract.js
USER app
EXPOSE 8081
CMD ["node", "public-pages/server.mjs"]

FROM nginx:1.27-alpine AS frontend

RUN addgroup -S -g 10001 app && \
    adduser -S -D -H -u 10001 -G app app && \
    mkdir -p /var/cache/nginx /var/run && \
    touch /var/run/nginx.pid && \
    chown -R app:app /var/cache/nginx && \
    chown app:app /var/run/nginx.pid

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist-server/public-routes.inc /etc/nginx/public-routes.inc
COPY docker/check-public-pages-build.sh /usr/local/bin/check-public-pages-build.sh
RUN sed -i 's/\r$//' /usr/local/bin/check-public-pages-build.sh

USER app
EXPOSE 8080
CMD ["sh", "/usr/local/bin/check-public-pages-build.sh"]
