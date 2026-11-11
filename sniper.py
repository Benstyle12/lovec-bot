import os
import sys
import time
import requests
import oci
from datetime import datetime

# ==========================================
# KONFIGURACE Z ENVIRONMENT VARIABLES
# ==========================================
USER_OCID = os.environ.get("OCI_USER_OCID")
TENANCY_OCID = os.environ.get("OCI_TENANCY_OCID")
FINGERPRINT = os.environ.get("OCI_FINGERPRINT")
KEY_CONTENT = os.environ.get("OCI_KEY_CONTENT")
REGION = os.environ.get("OCI_REGION", "eu-frankfurt-1")

COMPARTMENT_OCID = os.environ.get("OCI_COMPARTMENT_OCID") or TENANCY_OCID
SUBNET_OCID = os.environ.get("OCI_SUBNET_OCID")
IMAGE_OCID = os.environ.get("OCI_IMAGE_OCID")
AVAILABILITY_DOMAIN = os.environ.get("OCI_AVAILABILITY_DOMAIN")
SSH_PUBLIC_KEY = os.environ.get("OCI_SSH_PUBLIC_KEY", "")

OCPUS = float(os.environ.get("INSTANCE_OCPUS", "2"))
MEMORY_IN_GBS = float(os.environ.get("INSTANCE_MEMORY_GBS", "12"))
BOOT_VOLUME_GB = int(os.environ.get("BOOT_VOLUME_GB", "50"))
INSTANCE_NAME = os.environ.get("INSTANCE_NAME", "oracle-free-ampere")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Doba běhu skriptu v sekundách (pro GitHub Actions doporučeno ~45-50 minut, pak workflow skončí nebo se spustí znovu)
MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", "45"))
RETRY_DELAY_SECONDS = int(os.environ.get("RETRY_DELAY_SECONDS", "30"))


def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def send_notification(message):
    log(f"Posílám notifikaci: {message}")
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        except Exception as e:
            log(f"Chyba při odesílání Discord webhooku: {e}")

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        except Exception as e:
            log(f"Chyba při odesílání Telegram zprávy: {e}")


def validate_env():
    missing = []
    if not USER_OCID: missing.append("OCI_USER_OCID")
    if not TENANCY_OCID: missing.append("OCI_TENANCY_OCID")
    if not FINGERPRINT: missing.append("OCI_FINGERPRINT")
    if not KEY_CONTENT: missing.append("OCI_KEY_CONTENT")
    if not SUBNET_OCID: missing.append("OCI_SUBNET_OCID")
    if not IMAGE_OCID: missing.append("OCI_IMAGE_OCID")

    if missing:
        log(f"CHYBA: Chybí povinné proměnné prostředí: {', '.join(missing)}")
        sys.exit(1)


def get_oci_clients():
    config = {
        "user": USER_OCID,
        "key_content": KEY_CONTENT,
        "fingerprint": FINGERPRINT,
        "tenancy": TENANCY_OCID,
        "region": REGION
    }
    oci.config.validate_config(config)
    compute_client = oci.core.ComputeClient(config)
    identity_client = oci.identity.IdentityClient(config)
    return compute_client, identity_client


def resolve_availability_domains(identity_client):
    if AVAILABILITY_DOMAIN:
        return [AVAILABILITY_DOMAIN]
    
    log("Zjišťuji dostupné Availability Domains (AD)...")
    try:
        ads = identity_client.list_availability_domains(compartment_id=COMPARTMENT_OCID).data
        ad_names = [ad.name for ad in ads]
        log(f"Nalezeno {len(ad_names)} AD: {ad_names}")
        return ad_names
    except Exception as e:
        log(f"Chyba při zjišťování AD: {e}")
        return []


def create_instance(compute_client, ad_name):
    shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
        ocpus=OCPUS,
        memory_in_gbs=MEMORY_IN_GBS
    )

    source_details = oci.core.models.InstanceSourceViaImageDetails(
        source_type="image",
        image_id=IMAGE_OCID,
        boot_volume_size_in_gbs=BOOT_VOLUME_GB
    )

    vnic_details = oci.core.models.CreateVnicDetails(
        subnet_id=SUBNET_OCID,
        assign_public_ip=True
    )

    metadata = {}
    if SSH_PUBLIC_KEY:
        metadata["ssh_authorized_keys"] = SSH_PUBLIC_KEY.strip()

    launch_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=COMPARTMENT_OCID,
        availability_domain=ad_name,
        shape="VM.Standard.A1.Flex",
        shape_config=shape_config,
        source_details=source_details,
        create_vnic_details=vnic_details,
        display_name=INSTANCE_NAME,
        metadata=metadata
    )

    return compute_client.launch_instance(launch_details)


def main():
    validate_env()
    log("==================================================")
    log(f"Spouštím OCI Sniper pro {OCPUS} OCPU a {MEMORY_IN_GBS} GB RAM...")
    log(f"Region: {REGION}")
    log("==================================================")

    compute_client, identity_client = get_oci_clients()
    ad_list = resolve_availability_domains(identity_client)

    if not ad_list:
        log("Nepodařilo se najít žádnou Availability Domain! Zkontroluj oprávnění/nastavení.")
        sys.exit(1)

    start_time = time.time()
    max_duration = MAX_RUNTIME_MINUTES * 60
    attempt = 0

    while True:
        elapsed = time.time() - start_time
        if elapsed >= max_duration:
            log(f"Dosažen časový limit běhu ({MAX_RUNTIME_MINUTES} minut). Ukončuji tento běh.")
            break

        for ad in ad_list:
            attempt += 1
            log(f"Pokus #{attempt} (AD: {ad})... Pokouším se vytvořit instanci...")

            try:
                response = create_instance(compute_client, ad)
                instance = response.data
                msg = (
                    f"🎉🎉 BOOM! INSTANCE ÚSPĚŠNĚ VYTVOŘENA! 🎉🎉\n"
                    f"Název: {instance.display_name}\n"
                    f"OCID: {instance.id}\n"
                    f"Stav: {instance.lifecycle_state}\n"
                    f"AD: {ad}\n"
                    f"OCPU: {OCPUS}, RAM: {MEMORY_IN_GBS} GB"
                )
                log(msg)
                send_notification(msg)
                print("::notice title=Instance Created::Instance was successfully created in Oracle Cloud!")
                sys.exit(0)

            except oci.exceptions.ServiceError as e:
                # OCI vrací 500 Out of host capacity nebo OutOfCapacity
                if "Out of host capacity" in str(e) or e.status in (500, 502, 503) or "capacity" in str(e).lower():
                    log(f"⏳ Kapacita v {ad} je stále vyčerpaná (Out of host capacity).")
                elif "LimitExceeded" in str(e) or "TooManyRequests" in str(e) or e.status == 429:
                    log(f"⚠️ Rate limit nebo limit překročen: {e.message}")
                else:
                    log(f"❌ OCI Chyba ({e.status} - {e.code}): {e.message}")
            except Exception as e:
                log(f"❌ Neočekávaná chyba: {e}")

            time.sleep(RETRY_DELAY_SECONDS)

    log("Běh dokončen bez ulovení. Příští GitHub Action se postará o další pokusy!")


if __name__ == "__main__":
    main()
