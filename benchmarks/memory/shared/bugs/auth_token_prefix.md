# Auth Token Format

## Correct Format
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Wrong Format
```
Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Issue Details
- The `Bearer` prefix is **required** for OAuth 2.0 Bearer Token authentication
- Missing the prefix will cause 401 Unauthorized responses
- This is defined in RFC 6750

## Integration Points
- All API clients must include the Bearer prefix
- Backend validation expects `Bearer ` (with space) before the token
- Token refresh flows must preserve the correct format
