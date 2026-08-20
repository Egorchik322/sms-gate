#include <gammu/gammu-smsd.h>
#include <gammu/gammu-info.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *network_state_name(GSM_NetworkInfo_State state) {
    switch (state) {
    case GSM_HomeNetwork: return "home";
    case GSM_NoNetwork: return "no_network";
    case GSM_RoamingNetwork: return "roaming";
    case GSM_RegistrationDenied: return "registration_denied";
    case GSM_NetworkStatusUnknown: return "unknown";
    case GSM_RequestingNetwork: return "requesting";
    default: return "unknown";
    }
}

static const char *gprs_state_name(GSM_GPRS_State state) {
    switch (state) {
    case GSM_GPRS_Detached: return "detached";
    case GSM_GPRS_Attached: return "attached";
    default: return "unknown";
    }
}

static void json_string(const char *value) {
    putchar('"');
    if (value != NULL) {
        for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
            if (*p == '"' || *p == '\\') {
                putchar('\\');
                putchar(*p);
            } else if (*p >= 0x20 && *p < 0x7f) {
                putchar(*p);
            }
        }
    }
    putchar('"');
}

static void json_network_name(const unsigned char *value) {
    char name[sizeof(((GSM_NetworkInfo *)0)->NetworkName) + 1];
    size_t out = 0;
    memset(name, 0, sizeof(name));
    if (value != NULL) {
        for (size_t i = 0; i + 1 < sizeof(((GSM_NetworkInfo *)0)->NetworkName); i += 2) {
            unsigned char high = value[i];
            unsigned char low = value[i + 1];
            unsigned char c = high == 0 ? low : (low == 0 ? high : 0);
            if (c == 0) break;
            if (c >= 0x20 && c < 0x7f && out + 1 < sizeof(name)) {
                name[out++] = (char)c;
            }
        }
    }
    name[out] = '\0';
    json_string(name);
}

static void json_optional_string(const char *value) {
    if (value != NULL && value[0] != '\0') json_string(value);
    else fputs("null", stdout);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s /path/to/gammu-smsdrc\n", argv[0]);
        return 2;
    }

    GSM_SMSDConfig *config = SMSD_NewConfig("gammu-smsd-status");
    if (config == NULL) {
        fprintf(stderr, "SMSD_NewConfig failed\n");
        return 1;
    }

    GSM_Error error = SMSD_ReadConfig(argv[1], config, FALSE);
    if (error != ERR_NONE) {
        fprintf(stderr, "SMSD_ReadConfig failed: %d\n", error);
        SMSD_FreeConfig(config);
        return 1;
    }

    GSM_SMSDStatus status;
    memset(&status, 0, sizeof(status));
    error = SMSD_GetStatus(config, &status);
    if (error != ERR_NONE) {
        fprintf(stderr, "SMSD_GetStatus failed: %d\n", error);
        SMSD_FreeConfig(config);
        return 1;
    }

    printf("{\"version\":%d,\"client\":", status.Version);
    json_optional_string(status.Client);
    printf(",\"phone_id\":");
    json_optional_string(status.PhoneID);
    printf(",\"signal_percent\":%d,\"signal_dbm\":%d,\"bit_error_percent\":%d", status.Network.SignalPercent, status.Network.SignalStrength, status.Network.BitErrorRate);
    printf(",\"sent\":%d,\"received\":%d,\"failed\":%d", status.Sent, status.Received, status.Failed);
    printf(",\"network_name\":");
    json_network_name(status.NetInfo.NetworkName);
    printf(",\"network_code\":");
    json_optional_string(status.NetInfo.NetworkCode);
    printf(",\"network_state\":");
    json_string(network_state_name(status.NetInfo.State));
    printf(",\"lac\":");
    json_optional_string(status.NetInfo.LAC);
    printf(",\"cid\":");
    json_optional_string(status.NetInfo.CID);
    printf(",\"gprs_state\":");
    json_string(gprs_state_name(status.NetInfo.GPRS));
    printf(",\"packet_state\":");
    json_string(network_state_name(status.NetInfo.PacketState));
    printf(",\"packet_lac\":");
    json_optional_string(status.NetInfo.PacketLAC);
    printf(",\"packet_cid\":");
    json_optional_string(status.NetInfo.PacketCID);
    printf("}\n");

    SMSD_FreeConfig(config);
    return 0;
}
