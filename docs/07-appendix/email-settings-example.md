# Email Settings Configuration Example

This document shows the structure and format of email notification settings.

## Configuration Schema

Email settings are stored in the settings database under the `email` category.

### Fields

| Field                     | Type    | Default            | Description                                   |
| ------------------------- | ------- | ------------------ | --------------------------------------------- |
| `enabled`                 | boolean | `false`            | Enable/disable email notifications            |
| `smtp_server`             | string  | `"smtp.qq.com"`    | SMTP server address                           |
| `smtp_port`               | integer | `465`              | SMTP port (465 for SSL, 587 for TLS)          |
| `sender_email`            | string  | _required_         | Sender email address                          |
| `sender_password`         | string  | _required_         | SMTP password or app-specific password        |
| `sender_name`             | string  | `"WeCom 同步系统"` | Display name for sender                       |
| `receiver_email`          | string  | _required_         | Recipient email address                       |
| `notify_on_voice`         | boolean | `true`             | Send email when customer sends voice message  |
| `notify_on_human_request` | boolean | `true`             | Send email when customer requests human agent |

## Example Configuration

```json
{
  "enabled": true,
  "smtp_server": "smtp.qq.com",
  "smtp_port": 465,
  "sender_email": "your-email@qq.com",
  "sender_password": "your-app-password",
  "sender_name": "WeCom 同步系统",
  "receiver_email": "recipient@gmail.com",
  "notify_on_voice": true,
  "notify_on_human_request": true
}
```

## SMTP Server Examples

### QQ Mail

```json
{
  "smtp_server": "smtp.qq.com",
  "smtp_port": 465,
  "sender_email": "your@qq.com",
  "sender_password": "authorization_code"
}
```

**Note**: QQ Mail requires an authorization code, not the account password.
Get it from: QQ Mail Settings → Account → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV Services

### Gmail

```json
{
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "sender_email": "your@gmail.com",
  "sender_password": "app_password"
}
```

**Note**: Gmail requires App Passwords.
Enable 2FA → Generate App Password at: https://myaccount.google.com/apppasswords

### 163 Mail

```json
{
  "smtp_server": "smtp.163.com",
  "smtp_port": 465,
  "sender_email": "your@163.com",
  "sender_password": "authorization_code"
}
```

## Security Best Practices

1. **Use App-Specific Passwords**: Don't use your main account password
2. **Enable SSL/TLS**: Always use encrypted connections
3. **Limit Access**: Only enable notifications when needed
4. **Rotate Passwords**: Change SMTP passwords regularly
5. **Monitor Usage**: Check email sending logs for unusual activity

## Testing Configuration

Use the API to test email settings:

```bash
# Test email sending
curl -X POST http://localhost:8765/settings/email/test \
  -H "Content-Type: application/json" \
  -d '{
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "sender_email": "your@qq.com",
    "sender_password": "your-password",
    "sender_name": "WeCom 同步系统",
    "receiver_email": "recipient@gmail.com"
  }'
```

## Notification Triggers

### Voice Message Notification

Sent when a customer sends a voice message:

- Subject: `🎤 用户发语音通知 - {customer_name}`
- Includes: Customer name, channel, device serial, timestamp
- Action: Automatically adds customer to blacklist

### Human Request Notification

Sent when AI detects a customer wants to speak with a human:

- Subject: `🙋 用户转人工通知 - {customer_name}`
- Includes: Customer name, channel, device serial, reason
- Action: Automatically adds customer to blacklist

## Troubleshooting

### Authentication Failed

**Error**: `认证失败，请检查邮箱和授权码`

**Solutions**:

- Verify sender_password is correct
- For QQ Mail: Use authorization code, not account password
- For Gmail: Use App Password, not account password
- Check if SMTP service is enabled in email settings

### Connection Failed

**Error**: `连接服务器失败`

**Solutions**:

- Verify smtp_server and smtp_port
- Check firewall settings
- Try alternative port (465 for SSL, 587 for TLS)
- Test SMTP connectivity: `telnet smtp.qq.com 465`

### Email Not Received

**Checks**:

1. Check spam/junk folder
2. Verify receiver_email address
3. Check email quota limits
4. Verify `enabled` is set to `true`
5. Check notification triggers (`notify_on_voice`, `notify_on_human_request`)

## API Endpoints

| Method | Endpoint                        | Description                   |
| ------ | ------------------------------- | ----------------------------- |
| GET    | `/settings/email/settings`      | Get current email settings    |
| PUT    | `/settings/email/settings`      | Save email settings           |
| POST   | `/settings/email/test`          | Test email configuration      |
| POST   | `/settings/email/human-request` | Manual trigger: human request |
| POST   | `/settings/email/voice-message` | Manual trigger: voice message |

## Database Storage

Settings are stored in the settings database:

```sql
-- Query email settings
SELECT * FROM settings WHERE category = 'email';

-- Update individual setting
UPDATE settings
SET value = 'true', updated_by = 'user', updated_at = datetime('now')
WHERE category = 'email' AND key = 'enabled';
```

## Migration Notes

**Previous System** (Deprecated):

- Configuration file: `wecom-desktop/backend/email_settings.json`
- Direct file I/O
- No change tracking
- Security risk (plain text passwords)

**Current System** (Active):

- Database storage (SQLite)
- Change tracking (who changed what, when)
- Type-safe (Pydantic models)
- Better security (encryption potential)

The old `email_settings.json` file was removed on 2026-02-06 as part of the migration to database-based settings.
