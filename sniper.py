import os
import sys
import time
import requests
import re
import oci
from datetime import datetime

# Zajistit bezchybný výpis UTF-8 znaků (emojis a čeština) na všech systémech
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def clean_pem_key(k):
    if not k:
        return k
    k = k.strip()
    k = k.replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    # Filtrujeme případné zbloudilé řádky a vytáhneme tělo klíče
    lines = [l.strip() for l in k.splitlines() if l.strip() and not l.startswith("-----") and l.strip() != "OCI_API_KEY"]
    body = "\n".join(lines)
    return "-----BEGIN PRIVATE KEY-----\n" + body + "\n-----END PRIVATE KEY-----\n"

# ==========================================
# KONFIGURACE Z ENVIRONMENT VARIABLES
# ==========================================
USER_OCID = os.environ.get("OCI_USER_OCID")
TENANCY_OCID = os.environ.get("OCI_TENANCY_OCID")
FINGERPRINT = os.environ.get("OCI_FINGERPRINT")
KEY_CONTENT = os.environ.get("OCI_KEY_CONTENT")
KEY_FILE_PATH = os.path.expanduser("~/.oci/oci_api_key.pem")

if os.path.exists(KEY_FILE_PATH) and os.path.getsize(KEY_FILE_PATH) > 0:
    try:
        with open(KEY_FILE_PATH, "r", encoding="utf-8") as f:
            file_key = f.read().strip()
            if len(file_key) > 50:
                KEY_CONTENT = file_key
    except Exception as e:
        pass

REGION = os.environ.get("OCI_REGION", "eu-turin-1")

COMPARTMENT_OCID = os.environ.get("OCI_COMPARTMENT_OCID") or TENANCY_OCID
SUBNET_OCID = os.environ.get("OCI_SUBNET_OCID")
VCN_OCID = os.environ.get("OCI_VCN_OCID")
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

MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", "28"))
RETRY_DELAY_SECONDS = int(os.environ.get("RETRY_DELAY_SECONDS", "20"))


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
    if not SUBNET_OCID and not VCN_OCID: missing.append("OCI_SUBNET_OCID (nebo OCI_VCN_OCID)")

    if missing:
        log(f"CHYBA: Chybí povinné proměnné prostředí: {', '.join(missing)}")
        sys.exit(1)


def get_oci_clients():
    cleaned_key = clean_pem_key(KEY_CONTENT)
    if not cleaned_key:
        log("CHYBA: OCI_KEY_CONTENT je prázdný!")
        sys.exit(1)

    log(f"Klíč načten (délka: {len(cleaned_key)} znaků).")
    header_preview = cleaned_key[:27].replace('\n', ' ')
    footer_preview = cleaned_key[-27:].replace('\n', ' ')
    log(f"Formát klíče: začátek='{header_preview}' ... konec='{footer_preview}'")

    config = {
        "user": USER_OCID,
        "key_content": cleaned_key,
        "fingerprint": FINGERPRINT,
        "tenancy": TENANCY_OCID,
        "region": REGION
    }
    oci.config.validate_config(config)
    compute_client = oci.core.ComputeClient(config)
    identity_client = oci.identity.IdentityClient(config)
    vn_client = oci.core.VirtualNetworkClient(config)
    return compute_client, identity_client, vn_client


def resolve_subnet(vn_client):
    global SUBNET_OCID
    if SUBNET_OCID and SUBNET_OCID.startswith("ocid1.subnet."):
        return SUBNET_OCID

    target_vcn = VCN_OCID
    if SUBNET_OCID and SUBNET_OCID.startswith("ocid1.vcn."):
        target_vcn = SUBNET_OCID

    log(f"Automaticky vyhledávám veřejný Subnet pro VCN ({target_vcn})...")
    try:
        subnets = vn_client.list_subnets(compartment_id=COMPARTMENT_OCID, vcn_id=target_vcn).data
        if not subnets:
            subnets = vn_client.list_subnets(compartment_id=COMPARTMENT_OCID).data

        for s in subnets:
            if not s.prohibit_public_ip_on_vnic:
                log(f"Nalezen veřejný Subnet: {s.display_name} ({s.id})")
                SUBNET_OCID = s.id
                return s.id

        if subnets:
            SUBNET_OCID = subnets[0].id
            log(f"Používám Subnet: {subnets[0].display_name} ({SUBNET_OCID})")
            return SUBNET_OCID
    except Exception as e:
        log(f"Chyba při hledání Subnetu: {e}")

    return SUBNET_OCID


def resolve_image(compute_client):
    global IMAGE_OCID
    if IMAGE_OCID:
        return IMAGE_OCID

    log("Automaticky vyhledávám nejnovější Ubuntu ARM (aarch64) Image...")
    try:
        images = compute_client.list_images(
            compartment_id=COMPARTMENT_OCID,
            operating_system="Canonical Ubuntu",
            shape="VM.Standard.A1.Flex",
            sort_by="TIMECREATED",
            sort_order="DESC"
        ).data

        for img in images:
            if "aarch64" in img.display_name.lower() or "arm" in img.display_name.lower():
                log(f"Nalezen Ubuntu ARM Image: {img.display_name} ({img.id})")
                IMAGE_OCID = img.id
                return IMAGE_OCID

        if images:
            IMAGE_OCID = images[0].id
            log(f"Používám Image: {images[0].display_name} ({IMAGE_OCID})")
            return IMAGE_OCID
    except Exception as e:
        log(f"Chyba při hledání Image: {e}")

    return IMAGE_OCID


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


def create_instance(compute_client, ad_name, subnet_id, image_id):
    shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
        ocpus=OCPUS,
        memory_in_gbs=MEMORY_IN_GBS
    )

    source_details = oci.core.models.InstanceSourceViaImageDetails(
        source_type="image",
        image_id=image_id,
        boot_volume_size_in_gbs=BOOT_VOLUME_GB
    )

    vnic_details = oci.core.models.CreateVnicDetails(
        subnet_id=subnet_id,
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

    compute_client, identity_client, vn_client = get_oci_clients()
    
    subnet_id = resolve_subnet(vn_client)
    if not subnet_id:
        log("CHYBA: Nepodařilo se zjistit Subnet OCID!")
        sys.exit(1)

    image_id = resolve_image(compute_client)
    if not image_id:
        log("CHYBA: Nepodařilo se zjistit Image OCID!")
        sys.exit(1)

    ad_list = resolve_availability_domains(identity_client)
    if not ad_list:
        log("CHYBA: Nepodařilo se najít žádnou Availability Domain!")
        sys.exit(1)

    start_time = time.time()
    max_duration = MAX_RUNTIME_MINUTES * 60
    attempt = 0

    while True:
        elapsed = time.time() - start_time
        if elapsed >= max_duration:
            log(f"Dosažen časový limit běhu ({MAX_RUNTIME_MINUTES} minut). Tento běh končí, další běh začne brzy.")
            break

        for ad in ad_list:
            attempt += 1
            log(f"Pokus #{attempt} (AD: {ad})... Pokouším se vytvořit instanci...")

            try:
                response = create_instance(compute_client, ad, subnet_id, image_id)
                instance = response.data
                msg = (
                    f"🎉🎉 BOOM! INSTANCE ÚSPĚŠNĚ VYTVOŘENA! 🎉🎉\n"
                    f"Název: {instance.display_name}\n"
                    f"OCID: {instance.id}\n"
                    f"Stav: {instance.lifecycle_state}\n"
                    f"AD: {ad}\n"
                    f"OCPU: {OCPUS}, RAM: {MEMORY_IN_GBS} GB\n"
                    f"Region: {REGION}"
                )
                log(msg)
                send_notification(msg)
                print("::notice title=Instance Created::Instance was successfully created in Oracle Cloud!")
                sys.exit(0)

            except oci.exceptions.ServiceError as e:
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
    try:
        main()
    except Exception as e:
        import traceback
        err_details = traceback.format_exc()
        log(f"KRITICKÁ CHYBA:\n{err_details}")
        send_notification(f"❌ Chyba při spuštění bota:\n{str(e)[:300]}")
        sys.exit(1)
