# ============================================================
# Fiber Agent Frontend — Multi-stage Build
# Stage 1: Node.js 构建
# Stage 2: Nginx 静态服务 + 反向代理
# ============================================================

FROM node:20-alpine AS builder

WORKDIR /app

# 依赖缓存层
COPY package.json ./
RUN npm install --registry=https://registry.npmmirror.com

# 源码构建
COPY . .
RUN npm run build

# ============================================================
FROM nginx:1.25-alpine AS production

# Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
