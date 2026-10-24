FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG API_URL=http://api:8000
ENV API_URL=$API_URL
RUN npm run build

FROM node:22-slim
WORKDIR /app
COPY --from=build /app ./
ENV API_URL=http://api:8000
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
