# 🏹 Oracle Cloud Free Ampere (A1) Instance Sniper

Automatický bot pro ulovení bezplatné instance **Oracle Cloud Always Free (Ampere A1 Flex - 2 OCPU, 12 GB RAM)**, běžící přímo na **GitHub Actions** bez nutnosti vlastního serveru.

---

## 🚀 Jak to funguje?
1. Bot běží v GitHub Actions automaticky (každých 30 minut) nebo na ruční spuštění.
2. V každém běhu zkouší po dobu 28 minut posílat požadavky na Oracle Cloud API.
3. Pokud Oracle vrátí chybu `Out of host capacity`, bot počká 20 sekund a zkusí to znovu.
4. Jakmile se uvolní kapacita a server se vytvoří, bot pošle notifikaci na **Discord / Telegram** a ukončí se!

---

## 🔑 Seznam požadovaných GitHub Secrets

V repozitáři přejdi do **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**:

| Secret | Popis | Příklad |
|---|---|---|
| `OCI_USER_OCID` | OCID tvého uživatele | `ocid1.user.oc1..aaaa...` |
| `OCI_TENANCY_OCID` | OCID tvého tenancy (účtu) | `ocid1.tenancy.oc1..aaaa...` |
| `OCI_FINGERPRINT` | Otisk tvého API klíče | `12:34:56:...` |
| `OCI_KEY_CONTENT` | Celý privátní klíč (PEM) | `-----BEGIN RSA PRIVATE KEY----- ...` |
| `OCI_REGION` | Tvůj domovský region | `eu-frankfurt-1`, `eu-amsterdam-1` |
| `OCI_SUBNET_OCID` | OCID tvé virtuální podsítě (Subnet) | `ocid1.subnet.oc1...` |
| `OCI_IMAGE_OCID` | OCID image OS (např. Ubuntu 22.04 ARM) | `ocid1.image.oc1...` |
| `OCI_SSH_PUBLIC_KEY` | Tvůj veřejný SSH klíč pro přihlášení | `ssh-ed25519 AAAAC...` |

*(Volitelné: `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OCI_COMPARTMENT_OCID`, `OCI_AVAILABILITY_DOMAIN`)*
