---
name: api-design
description: Designing and testing REST/JSON HTTP APIs: resources, status codes, errors, pagination, auth, docs
triggers: rest api, restful, http api, json api, web api, api design, endpoint, endpoints, openapi, swagger, status code, status codes, pagination, webhook, curl, schnittstelle, api entwurf
---
# REST/JSON API design

1. **Resources are plural nouns**, verbs come from the HTTP method: `GET /items`, `POST /items`, `GET /items/{id}`, `PATCH /items/{id}`, `DELETE /items/{id}`. Nest at most one level (`/projects/{id}/tasks`). Use lowercase, hyphens, and one naming style for JSON keys (snake_case or camelCase, not both).
2. **Status codes.** 200 read or update, 201 created (with `Location` header), 204 no body, 400 malformed or invalid input, 401 not authenticated, 403 not allowed, 404 not found, 409 conflict, 422 valid JSON but semantic validation failed (pick 400 or 422 once and stay consistent), 429 rate limited. Never return 200 with an error inside.
3. **Validate every input** at the boundary: types, required fields, ranges, string length, enum values. Reject unknown fields or ignore them deliberately. Never trust ids, sizes or paths from the client.
4. **One error shape** everywhere: `{"error": {"code": "invalid_field", "message": "title must be 1-100 characters", "field": "title"}}`. Stable machine code, human message, no stack traces.
5. **Pagination** on every list: `?limit=50&offset=0` or a cursor. Default limit 50, maximum 200. Return the total or a `next` cursor. Sort deterministically (add the id as tie-breaker). Filters as query parameters.
6. **Idempotency.** GET, PUT, DELETE must be safe to repeat. For POST that must not duplicate (payments, orders) accept an `Idempotency-Key` header and store the result.
7. **Versioning.** Put it in the path (`/v1/`) from day one. Add fields freely; renaming or removing a field needs `/v2/`.
8. **Auth.** Token in the `Authorization: Bearer` header, never in the URL. Check authorization per resource on every request, not only login. HTTPS, CORS limited to known origins.
9. **Document with examples**: for each endpoint a method, path, request JSON, response JSON, and error cases, copied from real output.

**Test with curl** and keep the commands in the docs:
`curl -sS -i -X POST localhost:8000/v1/items -H 'Content-Type: application/json' -d '{"title":"x"}'`
Check the status line, headers and body. Test the happy path, a missing field, a wrong type, a nonexistent id, no auth, and an oversized body.

Avoid: verbs in paths (`/getItems`), returning unbounded lists, different error formats per endpoint, leaking database ids or internal messages, breaking changes without a version.
