"""
fashionvoid-bot · notifications/email_alert.py
─────────────────────────────────────────────────────────────────────────────
SMTP email notifier with a sleek HTML email template.

Sends a rich HTML email for every new listing that passes filters.
Falls back to plain-text multipart if the recipient's client is ancient.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import smtplib
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

# ── HTML email template ───────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>FashionVoid Alert</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="580" cellpadding="0" cellspacing="0"
               style="background:#111;border:1px solid #222;border-radius:4px;overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="background:#0a0a0a;padding:28px 36px;border-bottom:1px solid #1a1a1a;">
              <p style="margin:0;font-size:10px;letter-spacing:4px;color:#555;text-transform:uppercase;">
                FashionVoid Monitor
              </p>
              <h1 style="margin:6px 0 0;font-size:22px;font-weight:300;color:#e8e8e8;letter-spacing:1px;">
                {suspicious_banner}New Listing Detected
              </h1>
            </td>
          </tr>

          <!-- Image -->
          {image_block}

          <!-- Details -->
          <tr>
            <td style="padding:32px 36px;">

              <!-- Platform badge -->
              <p style="margin:0 0 16px;font-size:10px;letter-spacing:3px;
                         color:#888;text-transform:uppercase;">{platform}</p>

              <!-- Title -->
              <h2 style="margin:0 0 6px;font-size:18px;font-weight:400;
                          color:#e8e8e8;line-height:1.4;">{translated_title}</h2>
              <p style="margin:0 0 24px;font-size:12px;color:#555;font-style:italic;">
                {original_title}
              </p>

              <!-- Price block -->
              <table cellpadding="0" cellspacing="0"
                     style="background:#0d0d0d;border:1px solid #1e1e1e;
                             border-radius:3px;width:100%;margin-bottom:24px;">
                <tr>
                  <td style="padding:20px 24px;">
                    <p style="margin:0 0 4px;font-size:10px;letter-spacing:3px;
                               color:#555;text-transform:uppercase;">Price</p>
                    <p style="margin:0;font-size:28px;font-weight:300;color:#e8e8e8;">
                      {price_eur_str}
                    </p>
                    <p style="margin:4px 0 0;font-size:12px;color:#555;">
                      {price_original_str}
                    </p>
                  </td>
                  <td style="padding:20px 24px;border-left:1px solid #1e1e1e;">
                    <p style="margin:0 0 4px;font-size:10px;letter-spacing:3px;
                               color:#555;text-transform:uppercase;">Condition</p>
                    <p style="margin:0;font-size:15px;color:#aaa;">{condition}</p>
                  </td>
                </tr>
              </table>

              {suspicious_block}

              <!-- CTA button -->
              <table cellpadding="0" cellspacing="0" style="margin:0 auto;">
                <tr>
                  <td align="center" style="background:#e8e8e8;border-radius:2px;">
                    <a href="{url}" target="_blank"
                       style="display:inline-block;padding:14px 36px;font-size:12px;
                               letter-spacing:3px;text-transform:uppercase;
                               color:#0a0a0a;text-decoration:none;font-weight:500;">
                      View Listing →
                    </a>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 36px;border-top:1px solid #1a1a1a;
                        text-align:center;">
              <p style="margin:0;font-size:10px;letter-spacing:2px;
                         color:#333;text-transform:uppercase;">
                FashionVoid · Asia Monitor · {timestamp}
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

_SUSPICIOUS_BLOCK = """\
<table cellpadding="0" cellspacing="0"
       style="background:#1a0a00;border:1px solid #3d1f00;border-radius:3px;
               width:100%;margin-bottom:24px;">
  <tr>
    <td style="padding:16px 20px;">
      <p style="margin:0;font-size:10px;letter-spacing:3px;color:#cc5500;
                 text-transform:uppercase;">⚠ Suspicious Price</p>
      <p style="margin:4px 0 0;font-size:12px;color:#886644;">
        This listing is priced more than 75% below the rolling average for
        this keyword group. Verify authenticity before purchasing.
      </p>
    </td>
  </tr>
</table>
"""

_IMAGE_BLOCK = """\
<tr>
  <td style="padding:0;max-height:320px;overflow:hidden;">
    <img src="{image_url}" alt="Listing image"
         style="width:100%;max-height:320px;object-fit:cover;display:block;" />
  </td>
</tr>
"""


class EmailAlert:
    """Sends rich HTML email alerts via SMTP."""

    def __init__(self, config: dict, db):
        self.cfg = config.get("alerts", {}).get("email", {})
        self.db = db
        self.enabled = self.cfg.get("enabled", False)

    async def send(self, listing: dict) -> bool:
        """Send an email alert for *listing*.  Returns True on success."""
        if not self.enabled:
            return False

        # Deduplication
        if self.db.alert_already_sent(listing["id"], listing["platform"], "email"):
            return False

        try:
            # Run blocking SMTP in a thread so we don't block the event loop
            success = await asyncio.get_event_loop().run_in_executor(
                None, self._send_sync, listing
            )
            self.db.log_alert(listing["id"], listing["platform"], "email", success)
            return success
        except Exception as exc:
            logger.error(f"[email] Failed: {exc}")
            self.db.log_alert(
                listing["id"], listing["platform"], "email",
                success=False, error_msg=str(exc)
            )
            return False

    def _send_sync(self, listing: dict) -> bool:
        """Blocking SMTP send (called from executor)."""
        price_eur = listing.get("price_eur")
        price_eur_str = f"€{price_eur:,.0f}" if price_eur else "N/A"
        price_original_str = (
            f"{listing['price']:,.0f} {listing['currency']}"
            if listing.get("currency")
            else ""
        )

        is_suspicious = listing.get("is_suspicious", False)
        suspicious_banner = "⚠ SUSPICIOUS PRICE — " if is_suspicious else ""
        suspicious_block = _SUSPICIOUS_BLOCK if is_suspicious else ""

        image_url = listing.get("image_url", "")
        image_block = _IMAGE_BLOCK.format(image_url=image_url) if image_url else ""

        platform_display = listing.get("platform", "").replace("_", " ").upper()

        html_body = _HTML_TEMPLATE.format(
            suspicious_banner=suspicious_banner,
            suspicious_block=suspicious_block,
            image_block=image_block,
            platform=platform_display,
            translated_title=listing.get("translated_title") or listing.get("title", ""),
            original_title=listing.get("title", ""),
            price_eur_str=price_eur_str,
            price_original_str=price_original_str,
            condition=listing.get("condition") or "Not specified",
            url=listing.get("url", "#"),
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        )

        plain_body = textwrap.dedent(f"""
            FashionVoid Monitor — New Listing

            Platform : {platform_display}
            Title    : {listing.get("translated_title") or listing.get("title")}
            Original : {listing.get("title")}
            Price    : {price_eur_str} ({price_original_str})
            Condition: {listing.get("condition") or "Not specified"}
            URL      : {listing.get("url")}
            {"⚠ SUSPICIOUS PRICE — verify authenticity" if is_suspicious else ""}
        """).strip()

        subject = (
            f"{'⚠ SUSPICIOUS — ' if is_suspicious else ''}"
            f"[{platform_display}] {listing.get('translated_title') or listing.get('title')} "
            f"— {price_eur_str}"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.cfg["sender"]
        msg["To"] = self.cfg["recipient"]
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(self.cfg["smtp_host"], self.cfg["smtp_port"]) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(self.cfg["sender"], self.cfg["password"])
            smtp.sendmail(
                self.cfg["sender"],
                self.cfg["recipient"],
                msg.as_string(),
            )

        logger.info(
            f"[email] Sent alert for {listing['id']} @ {listing['platform']}"
        )
        return True
