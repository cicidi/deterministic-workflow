# 用户身份认证 & Token 验证

> 属于 [确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 涵盖：OAuth / OIDC 登录、token 验证、user context 注入 agentState。

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | 初始 auth spec：OAuth/OIDC 登录、token 验证、user context、provider 集成 |
| 2026-06-17 | 0.2.0 | 简化为身份优先：聚焦 token 验证 + UserContext 注入；role-based 权限推迟到未来接口 |

---

## 1. 角色定位

每个工作流交互必须携带已验证的用户身份。框架**不**实现自己的认证系统——它验证标准 OAuth / OIDC provider 颁发的 token，并将 user context 注入 `agentState`。

```
User Request (含 Bearer token)
    │
    ▼
[Token Verification]  ← OAuth / OIDC provider (Auth0, Okta, Keycloak, ...)
    │
    ├── 无效 / 过期 → 401 Unauthorized
    │
    └── 有效 → 提取 user context
                    │
                    ▼
              agentState.user = UserContext {
                user_id, provider, auth_time
              }
                    │
                    ▼
              [Layer 1: UNDERSTAND]
```

### 1.1 框架不做什么

- ❌ **不是 identity provider** — 不存密码、不签发 token、不管理用户目录
- ❌ **不是 session manager** — session 管理委托给 OAuth provider 或应用层
- ❌ **不是 OAuth server** — 不实现 OAuth grant flow

### 1.2 框架做什么

- ✅ **验证 token** — JWT 签名、过期时间、issuer、audience
- ✅ **提取 user context** — 从 token claims 映射到 UserContext
- ✅ **注入 agentState** — 填充 `agentState.user` 用于权限执行和审计
- ✅ **传递给 tool 层** — tools 收到已验证的 user context
- ✅ **审计** — 每次工作流交互记录认证用户

---

## 2. Token 验证流程

### 2.1 支持的 Token 类型

| 类型 | 验证方式 | 适用场景 |
|------|----------|----------|
| **JWT (RS256/ES256)** | 从 JWKS endpoint 获取公钥 | 最常用，无状态验证 |
| **Opaque token** | Token introspection endpoint | 集中式 token 验证 |
| **API Key** | 与存储的 key 做 hash 比对 | 机器间通信、dev 环境 |

### 2.2 验证步骤

```
1. 从 Authorization: Bearer <token> 提取 token
2. 判断 token 类型：
     JWT → 用公钥验证签名 (JWKS)
     opaque → POST /introspect 到 provider
     API key → hash 比对
3. 验证 claims：
     exp  — 未过期
     iss  — 匹配预期 issuer
     aud  — 匹配预期 audience
4. 从 token claims 提取 UserContext
5. 注入 agentState.user
```

### 2.3 UserContext Schema

```
UserContext {
  user_id:         string        // 唯一用户标识
  auth_provider:   string        // "auth0" | "okta" | "keycloak" | "custom"
  auth_time:       datetime      // token 签发时间
  session_id?:     string        // 审计关联
}
```

---

## 3. 实现选项

### Option A: OIDC Provider — Auth0 / Okta / Keycloak（推荐）

依赖专用 identity provider。框架只做 token 验证。

| Provider | 协议 | 验证方式 |
|----------|------|----------|
| **Auth0** | OIDC (JWT RS256) | 公钥来自 `https://<domain>/.well-known/jwks.json` |
| **Okta** | OIDC (JWT RS256) | 公钥来自 `https://<domain>/oauth2/default/v1/keys` |
| **Keycloak** | OIDC (JWT RS256) | 公钥来自 `https://<domain>/realms/<realm>/protocol/openid-connect/certs` |
| **Google Identity** | OIDC (JWT RS256) | 公钥来自 `https://www.googleapis.com/oauth2/v3/certs` |

```yaml
# framework.yaml
auth:
  provider: auth0
  token_type: jwt
  issuer: "https://my-app.auth0.com/"
  audience: "https://api.my-app.com"
  jwks_uri: "https://my-app.auth0.com/.well-known/jwks.json"
  claims_mapping:
    user_id: sub
```

### Option B: Custom Token Issuer

框架调用自定义 introspection endpoint 验证每个 token。适用于遗留系统。

```yaml
auth:
  provider: custom
  token_type: opaque
  introspection_endpoint: "https://internal-auth.example.com/introspect"
  introspection_method: POST
  headers:
    Authorization: "Bearer ${INTROSPECTION_API_KEY}"
```

### Option C: API Key (Dev / Machine-to-Machine)

简单的 key 比对。不推荐用于生产环境用户认证。

```yaml
auth:
  provider: api_key
  token_type: api_key
  api_keys:
    - key: "${DEV_API_KEY}"
      user_id: dev-user
      env: dev
```

### 3.1 对比矩阵

| 维度 | Option A (OIDC Provider) | Option B (自定义 Introspect) | Option C (API Key) |
|------|--------------------------|------------------------------|---------------------|
| 身份来源 | 外部 (Auth0/Okta/Keycloak) | 自定义遗留系统 | 静态配置 |
| Token 类型 | JWT | Opaque | API Key |
| 验证方式 | 离线 (公钥) | 在线 (introspect 调用) | Hash 比对 |
| 延迟 | <1ms (缓存 JWKS) | ~50ms (HTTP 调用) | <1ms |
| 安全性 | 高 (签名 JWT) | 取决于 introspection provider | 低 (静态 key) |
| 适用场景 | 生产环境 | 遗留系统桥接 | Dev / M2M |

---

## 4. 环境特定 Auth

```yaml
auth:
  dev:
    provider: api_key
    api_keys:
      - key: "dev-token-123"
        user_id: dev-user

  e2e:
    provider: auth0
    token_type: jwt
    issuer: "https://e2e-auth.example.com/"

  prod:
    provider: auth0
    token_type: jwt
    issuer: "https://auth.example.com/"
```

---

## 5. Role-Based Access（接口预留）

以上所有身份校验回答的问题是：**"这个用户是谁？"** (Authentication)

**"这个用户能做什么？"** (Authorization / Role-Based Access Control) 推迟到未来接口。当前仅定义契约——实现将在后续 spec 补充。

### 5.1 RoleResolver 接口

```
RoleResolver {
  resolve(user_context: UserContext) → ResolvedRoles
}

ResolvedRoles {
  user_id:       string
  groups:        string[]    // 来自 IdP 的原始 group
  permissions:   string[]    // 映射后的权限
}
```

### 5.2 配置

```yaml
auth:
  role_resolution:
    source: jwt_groups           # jwt_groups | ldap | custom_api | static | none
  jwt_groups:
    groups_claim: groups         # token 中哪个 JWT claim 包含 group 信息
```

### 5.3 延期内容

| 问题 | 状态 |
|------|------|
| 如何将 IdP group 名映射到内部 tool/transition 权限 | 延期 |
| RoleResolver → pycasbin 的桥接 | 延期 |

---

## 6. 多租户隔离

```yaml
auth:
  multi_tenant: false
  tenant_claim: "https://my-app.com/tenant_id"
```

启用时，框架将 tenant_id 注入 agentState 并传递给所有 tool 调用。

---

## 7. 审计跟踪

```
AuthAuditEntry {
  timestamp:        datetime
  user_id:          string
  auth_provider:    string
  token_valid:      boolean
  action:           "token_verified" | "token_expired" | "token_invalid"
  workflow_id?:     string
}
```

---

## 8. 开放问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | JWKS key 应该在内存中缓存并设置 TTL，还是每次请求都获取？ | 延迟 vs key 轮换安全 |
| 2 | 多实例部署，token 验证应该在 API 网关集中处理还是每个实例独立验证？ | 架构复杂度 |
| 3 | 框架应支持 token 刷新（滑动过期）还是仅做初次验证？ | 长对话场景 |
| 4 | 如何在不重新登录的情况下处理 token 撤销？ | 安全合规 |
| 5 | 框架是否支持同时使用多个 auth provider？ | 企业部署灵活性 |
| 6 | RoleResolver 应该是插件架构（类似 rule engines）还是单个可配置模块？ | 扩展性 vs 简洁 |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — §4.4 Permission Model
- [Routing & Execution](./2026-06-17-routing-execution-layer-design.md) — §7 Permission Model details
- [Tool Ecosystem](./2026-06-17-tool-ecosystem.md) — §6 pycasbin permission engine
- [Environment Config](./2026-06-17-environment-config.md) — 环境特定 auth 设置
