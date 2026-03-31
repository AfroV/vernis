/*
 * hue-stream.c — Hue Entertainment API DTLS streaming client
 *
 * Opens a DTLS 1.2 PSK connection to a Hue Bridge and streams
 * HueStream color packets at up to 25 Hz.
 *
 * Reads color commands from stdin: "R G B\n" (0-255 each)
 * Streams to all channels in the entertainment area with that color.
 *
 * Usage:
 *   hue-stream <bridge_ip> <username> <clientkey_hex> <area_id> <num_channels>
 *
 * Compile:
 *   gcc -O2 -o hue-stream hue-stream.c -lssl -lcrypto
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <openssl/ssl.h>
#include <openssl/err.h>

#define HUE_PORT 2100
#define STREAM_HZ 25
#define KEEPALIVE_MS 9000
#define MAX_CHANNELS 10

static volatile int running = 1;

static void handle_signal(int sig) {
    (void)sig;
    running = 0;
}

/* PSK callback for DTLS */
static const char *g_psk_identity = NULL;
static unsigned char g_psk_key[64];
static int g_psk_key_len = 0;

static unsigned int psk_client_cb(SSL *ssl, const char *hint,
                                   char *identity, unsigned int max_identity_len,
                                   unsigned char *psk, unsigned int max_psk_len) {
    (void)ssl;
    (void)hint;

    strncpy(identity, g_psk_identity, max_identity_len - 1);
    identity[max_identity_len - 1] = '\0';

    if ((unsigned int)g_psk_key_len > max_psk_len)
        return 0;

    memcpy(psk, g_psk_key, g_psk_key_len);
    return g_psk_key_len;
}

/* Parse hex string to bytes */
static int hex_to_bytes(const char *hex, unsigned char *out, int max_len) {
    int len = strlen(hex);
    if (len % 2 != 0 || len / 2 > max_len)
        return -1;

    for (int i = 0; i < len / 2; i++) {
        unsigned int byte;
        if (sscanf(hex + 2 * i, "%2x", &byte) != 1)
            return -1;
        out[i] = (unsigned char)byte;
    }
    return len / 2;
}

/* Build HueStream v2 packet */
static int build_packet(unsigned char *buf, const char *area_id,
                        int num_channels, int r, int g, int b, int seq) {
    int pos = 0;

    /* Protocol header: "HueStream" */
    memcpy(buf + pos, "HueStream", 9);
    pos += 9;

    /* API version 2.0 */
    buf[pos++] = 0x02;
    buf[pos++] = 0x00;

    /* Sequence number */
    buf[pos++] = (unsigned char)(seq & 0xFF);

    /* Reserved */
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;

    /* Color mode: 0x00 = RGB */
    buf[pos++] = 0x00;

    /* Reserved */
    buf[pos++] = 0x00;

    /* Entertainment area ID (36 chars, padded to 36 bytes) */
    int id_len = strlen(area_id);
    if (id_len > 36) id_len = 36;
    memcpy(buf + pos, area_id, id_len);
    if (id_len < 36) memset(buf + pos + id_len, 0, 36 - id_len);
    pos += 36;

    /* Light channels — each gets the same color */
    /* 16-bit values: scale 0-255 to 0-65535 */
    unsigned short r16 = (unsigned short)(r * 257);  /* 255 * 257 = 65535 */
    unsigned short g16 = (unsigned short)(g * 257);
    unsigned short b16 = (unsigned short)(b * 257);

    for (int ch = 0; ch < num_channels && ch < MAX_CHANNELS; ch++) {
        buf[pos++] = (unsigned char)ch;         /* channel ID */
        buf[pos++] = (r16 >> 8) & 0xFF;        /* R high */
        buf[pos++] = r16 & 0xFF;               /* R low */
        buf[pos++] = (g16 >> 8) & 0xFF;        /* G high */
        buf[pos++] = g16 & 0xFF;               /* G low */
        buf[pos++] = (b16 >> 8) & 0xFF;        /* B high */
        buf[pos++] = b16 & 0xFF;               /* B low */
    }

    return pos;
}

/* Validate string contains only safe characters (alphanumeric, dash, dot, colon) */
static int is_safe_string(const char *s) {
    for (int i = 0; s[i]; i++) {
        char c = s[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '-' || c == '.' || c == ':'))
            return 0;
    }
    return 1;
}

/* Activate/deactivate entertainment area via REST API */
static int set_entertainment_active(const char *bridge_ip, const char *username,
                                     const char *area_id, int active) {
    /* Sanitize all inputs before passing to shell */
    if (!is_safe_string(bridge_ip) || !is_safe_string(username) || !is_safe_string(area_id)) {
        fprintf(stderr, "[hue-stream] Rejecting unsafe characters in arguments\n");
        return -1;
    }

    char cmd[512];
    snprintf(cmd, sizeof(cmd),
        "curl -s -k -X PUT 'https://%s/clip/v2/resource/entertainment_configuration/%s' "
        "-H 'hue-application-key: %s' "
        "-H 'Content-Type: application/json' "
        "-d '{\"action\": \"%s\"}' 2>/dev/null",
        bridge_ip, area_id, username, active ? "start" : "stop");

    FILE *fp = popen(cmd, "r");
    if (!fp) return -1;

    char buf[1024];
    while (fgets(buf, sizeof(buf), fp)) {
        /* Check for errors */
        if (strstr(buf, "error")) {
            fprintf(stderr, "[hue-stream] REST error: %s", buf);
        }
    }

    int ret = pclose(fp);
    fprintf(stderr, "[hue-stream] Entertainment area %s: %s (ret=%d)\n",
            area_id, active ? "activated" : "deactivated", ret);
    return ret;
}

static long long now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

int main(int argc, char *argv[]) {
    if (argc < 6) {
        fprintf(stderr, "Usage: %s <bridge_ip> <username> <clientkey_hex> <area_id> <num_channels>\n", argv[0]);
        return 1;
    }

    const char *bridge_ip = argv[1];
    const char *username = argv[2];
    const char *clientkey_hex = argv[3];
    const char *area_id = argv[4];
    int num_channels = atoi(argv[5]);

    if (num_channels < 1 || num_channels > MAX_CHANNELS) {
        fprintf(stderr, "[hue-stream] Invalid channel count: %d\n", num_channels);
        return 1;
    }

    /* Parse clientkey hex */
    g_psk_identity = username;
    g_psk_key_len = hex_to_bytes(clientkey_hex, g_psk_key, sizeof(g_psk_key));
    if (g_psk_key_len < 0) {
        fprintf(stderr, "[hue-stream] Invalid clientkey hex\n");
        return 1;
    }

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGPIPE, SIG_IGN);

    /* Initialize OpenSSL */
    SSL_library_init();
    SSL_load_error_strings();
    OpenSSL_add_ssl_algorithms();

    /* Activate entertainment area */
    fprintf(stderr, "[hue-stream] Activating entertainment area %s...\n", area_id);
    if (set_entertainment_active(bridge_ip, username, area_id, 1) != 0) {
        fprintf(stderr, "[hue-stream] Warning: failed to activate area (may already be active)\n");
    }
    usleep(500000); /* 500ms for bridge to prepare */

    /* Create DTLS context */
    const SSL_METHOD *method = DTLS_client_method();
    SSL_CTX *ctx = SSL_CTX_new(method);
    if (!ctx) {
        fprintf(stderr, "[hue-stream] SSL_CTX_new failed\n");
        ERR_print_errors_fp(stderr);
        return 1;
    }

    SSL_CTX_set_psk_client_callback(ctx, psk_client_cb);
    SSL_CTX_set_cipher_list(ctx, "PSK-AES128-GCM-SHA256");

    /* Create UDP socket */
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        perror("[hue-stream] socket");
        return 1;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(HUE_PORT);
    inet_pton(AF_INET, bridge_ip, &addr.sin_addr);

    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("[hue-stream] connect");
        return 1;
    }

    /* Create SSL object */
    SSL *ssl = SSL_new(ctx);
    if (!ssl) {
        fprintf(stderr, "[hue-stream] SSL_new failed\n");
        return 1;
    }

    /* Create BIO from socket */
    BIO *bio = BIO_new_dgram(sock, BIO_NOCLOSE);
    BIO_ctrl(bio, BIO_CTRL_DGRAM_SET_CONNECTED, 0, &addr);

    /* Set timeouts */
    struct timeval timeout;
    timeout.tv_sec = 5;
    timeout.tv_usec = 0;
    BIO_ctrl(bio, BIO_CTRL_DGRAM_SET_RECV_TIMEOUT, 0, &timeout);
    BIO_ctrl(bio, BIO_CTRL_DGRAM_SET_SEND_TIMEOUT, 0, &timeout);

    SSL_set_bio(ssl, bio, bio);

    /* DTLS handshake */
    fprintf(stderr, "[hue-stream] DTLS handshake with %s:%d...\n", bridge_ip, HUE_PORT);
    int ret = SSL_connect(ssl);
    if (ret != 1) {
        fprintf(stderr, "[hue-stream] DTLS handshake failed: %d\n", SSL_get_error(ssl, ret));
        ERR_print_errors_fp(stderr);
        SSL_free(ssl);
        SSL_CTX_free(ctx);
        close(sock);
        set_entertainment_active(bridge_ip, username, area_id, 0);
        return 1;
    }

    fprintf(stderr, "[hue-stream] DTLS connected! Streaming to %d channels at %d Hz\n",
            num_channels, STREAM_HZ);
    fprintf(stderr, "[hue-stream] Reading color commands from stdin (format: R G B)\n");

    /* Make stdin non-blocking */
    int flags = fcntl(STDIN_FILENO, F_GETFL, 0);
    fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK);

    int cur_r = 0, cur_g = 0, cur_b = 0;
    int seq = 0;
    long long last_send = 0;
    long long interval_ms = 1000 / STREAM_HZ;  /* 40ms for 25 Hz */
    char line[256];

    while (running) {
        /* Check for new color from stdin */
        if (fgets(line, sizeof(line), stdin) != NULL) {
            int nr, ng, nb;
            if (sscanf(line, "%d %d %d", &nr, &ng, &nb) == 3) {
                cur_r = nr < 0 ? 0 : (nr > 255 ? 255 : nr);
                cur_g = ng < 0 ? 0 : (ng > 255 ? 255 : ng);
                cur_b = nb < 0 ? 0 : (nb > 255 ? 255 : nb);
            } else if (strncmp(line, "QUIT", 4) == 0) {
                break;
            }
        } else {
            /* Clear EOF indicator for non-blocking stdin */
            if (feof(stdin)) clearerr(stdin);
        }

        /* Send at STREAM_HZ */
        long long now = now_ms();
        if (now - last_send >= interval_ms) {
            unsigned char packet[256];
            int pkt_len = build_packet(packet, area_id, num_channels,
                                       cur_r, cur_g, cur_b, seq);
            seq = (seq + 1) & 0xFF;

            ret = SSL_write(ssl, packet, pkt_len);
            if (ret <= 0) {
                int err = SSL_get_error(ssl, ret);
                if (err == SSL_ERROR_SYSCALL || err == SSL_ERROR_SSL) {
                    fprintf(stderr, "[hue-stream] SSL_write error: %d\n", err);
                    break;
                }
            }
            last_send = now;
        }

        /* Sleep a bit to avoid busy-waiting */
        usleep(5000);  /* 5ms */
    }

    fprintf(stderr, "[hue-stream] Shutting down...\n");

    /* Clean up */
    SSL_shutdown(ssl);
    SSL_free(ssl);
    SSL_CTX_free(ctx);
    close(sock);

    /* Deactivate entertainment area */
    set_entertainment_active(bridge_ip, username, area_id, 0);

    fprintf(stderr, "[hue-stream] Done.\n");
    return 0;
}
