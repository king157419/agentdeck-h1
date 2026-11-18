#pragma once

/**
 * @file deck_protocol.h
 * Pure C++17 AgentDeck v2 line-protocol parser, state store, and touch zone mapper.
 * Kept free of Arduino/LVGL dependencies so it can be unit-tested on the host PC.
 */

#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace agentdeck {

static constexpr int kNumSlots = 6;
static constexpr size_t kAgentNameMax = 8;
static constexpr size_t kNonceMax = 24;
static constexpr size_t kCmdSummaryMax = 96;
static constexpr size_t kHintMax = 96;
static constexpr size_t kSerialLineMax = 512;
static constexpr uint32_t kHeartbeatTimeoutMs = 3000;

enum class SlotState : uint8_t {
    STATE_IDLE = 0,
    STATE_RUN,
    STATE_ASK,
    STATE_DONE,
    STATE_ERR,
    STATE_GATE,
};

enum class RiskTier : uint8_t {
    TIER_NONE = 0,
    TIER_LOW,
    TIER_HIGH,
    TIER_CRITICAL,
};

struct SlotInfo {
    bool assigned = false;
    SlotState state = SlotState::STATE_IDLE;
    char name[kAgentNameMax + 1] = "--";
    uint32_t since_ms = 0;
};

struct ApprovalInfo {
    bool active = false;
    uint8_t slot = 0;  // 0 = unspecified, 1..6 = associated slot
    RiskTier tier = RiskTier::TIER_NONE;
    char nonce[kNonceMax + 1] = "-";
    char summary[kCmdSummaryMax + 1] = "";
};

struct DeviceModel {
    SlotInfo slots[kNumSlots];
    ApprovalInfo approval;
    bool hint_active = false;
    char hint[kHintMax + 1] = "";
    uint8_t selected_slot = 0;  // 0 = none, 1..6 = highlighted slot
    uint8_t brightness = 220;
    bool brightness_dirty = false;
    bool ui_dirty = true;

    bool heartbeat_seen = false;
    uint32_t last_heartbeat_ms = 0;

    void reset(uint32_t now_ms) {
        for (int i = 0; i < kNumSlots; ++i) {
            slots[i].assigned = false;
            slots[i].state = SlotState::STATE_IDLE;
            snprintf(slots[i].name, sizeof(slots[i].name), "--");
            slots[i].since_ms = now_ms;
        }
        clear_approval();
        clear_hint();
        selected_slot = 0;
        ui_dirty = true;
    }

    void clear_approval() {
        approval.active = false;
        approval.slot = 0;
        approval.tier = RiskTier::TIER_NONE;
        snprintf(approval.nonce, sizeof(approval.nonce), "-");
        approval.summary[0] = '\0';
        ui_dirty = true;
    }

    void clear_hint() {
        hint_active = false;
        hint[0] = '\0';
        ui_dirty = true;
    }

    bool is_hub_offline(uint32_t now_ms) const {
        if (!heartbeat_seen) {
            return false;
        }
        return static_cast<uint32_t>(now_ms - last_heartbeat_ms) > kHeartbeatTimeoutMs;
    }

    const char* shown_nonce() const {
        return approval.active ? approval.nonce : "-";
    }
};

inline const char* state_name(SlotState s) {
    switch (s) {
        case SlotState::STATE_RUN:  return "RUN";
        case SlotState::STATE_ASK:  return "ASK";
        case SlotState::STATE_DONE: return "DONE";
        case SlotState::STATE_ERR:  return "ERR";
        case SlotState::STATE_GATE: return "GATE";
        case SlotState::STATE_IDLE:
        default:                    return "IDLE";
    }
}

inline const char* tier_name(RiskTier t) {
    switch (t) {
        case RiskTier::TIER_LOW:      return "low";
        case RiskTier::TIER_HIGH:     return "high";
        case RiskTier::TIER_CRITICAL: return "critical";
        case RiskTier::TIER_NONE:
        default:                      return "none";
    }
}

inline bool str_ieq(const char* a, const char* b) {
    while (*a && *b) {
        if (tolower(static_cast<unsigned char>(*a)) != tolower(static_cast<unsigned char>(*b))) {
            return false;
        }
        ++a;
        ++b;
    }
    return *a == '\0' && *b == '\0';
}

inline bool parse_slot_state(const char* tok, SlotState* out) {
    if (str_ieq(tok, "RUN") || str_ieq(tok, "THINK") || str_ieq(tok, "TOOL")) {
        *out = SlotState::STATE_RUN;
        return true;
    }
    if (str_ieq(tok, "ASK") || str_ieq(tok, "WAIT") || str_ieq(tok, "INPUT")) {
        *out = SlotState::STATE_ASK;
        return true;
    }
    if (str_ieq(tok, "DONE")) {
        *out = SlotState::STATE_DONE;
        return true;
    }
    if (str_ieq(tok, "ERR") || str_ieq(tok, "ERROR")) {
        *out = SlotState::STATE_ERR;
        return true;
    }
    if (str_ieq(tok, "IDLE") || str_ieq(tok, "OFF") || str_ieq(tok, "EMPTY") || str_ieq(tok, "STALE")) {
        *out = SlotState::STATE_IDLE;
        return true;
    }
    if (str_ieq(tok, "GATE")) {
        *out = SlotState::STATE_GATE;
        return true;
    }
    return false;
}

inline bool parse_risk_tier(const char* tok, RiskTier* out) {
    if (str_ieq(tok, "low") || str_ieq(tok, "l0") || str_ieq(tok, "l1")) {
        *out = RiskTier::TIER_LOW;
        return true;
    }
    if (str_ieq(tok, "high") || str_ieq(tok, "l2")) {
        *out = RiskTier::TIER_HIGH;
        return true;
    }
    if (str_ieq(tok, "critical") || str_ieq(tok, "crit") || str_ieq(tok, "l3")) {
        *out = RiskTier::TIER_CRITICAL;
        return true;
    }
    return false;
}

inline void sanitize_ascii(const char* src, char* dst, size_t max_chars, bool allow_space, bool truncate_ellipsis = false) {
    if (!src || max_chars == 0) {
        if (dst) dst[0] = '\0';
        return;
    }
    while (*src == ' ' || *src == '\t') ++src;

    size_t out_i = 0;
    size_t src_i = 0;
    bool truncated = false;
    while (src[src_i] != '\0' && src[src_i] != '\r' && src[src_i] != '\n') {
        unsigned char ch = static_cast<unsigned char>(src[src_i++]);
        char mapped = '\0';
        if (ch >= 0x21 && ch <= 0x7E) {
            mapped = static_cast<char>(ch);
        } else if (allow_space && (ch == ' ' || ch == '\t')) {
            mapped = ' ';
        } else if (ch >= 0x80) {
            // Non-ASCII byte without CJK font loaded: collapse UTF-8 sequence to '?'
            if ((ch & 0xC0) != 0x80) {
                mapped = '?';
            } else {
                continue;
            }
        }
        if (mapped == '\0') continue;
        if (mapped == ' ' && out_i > 0 && dst[out_i - 1] == ' ') continue;

        if (out_i < max_chars) {
            dst[out_i++] = mapped;
        } else {
            truncated = true;
            break;
        }
    }
    while (out_i > 0 && dst[out_i - 1] == ' ') {
        --out_i;
    }
    if (truncated && truncate_ellipsis && max_chars >= 4) {
        size_t tail = (out_i >= 3) ? (out_i - 3) : 0;
        dst[tail] = '.';
        dst[tail + 1] = '.';
        dst[tail + 2] = '.';
        out_i = tail + 3;
    }
    dst[out_i] = '\0';
}

/* Extracts the next whitespace-delimited token and returns pointer to the rest of the line */
inline const char* next_token(const char* p, char* tok, size_t tok_size) {
    if (!p) {
        tok[0] = '\0';
        return "";
    }
    while (*p == ' ' || *p == '\t') ++p;
    size_t i = 0;
    while (*p != '\0' && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') {
        if (i + 1 < tok_size) {
            tok[i++] = *p;
        }
        ++p;
    }
    tok[i] = '\0';
    while (*p == ' ' || *p == '\t') ++p;
    return p;
}

inline bool parse_int_range(const char* tok, int min_v, int max_v, int* out) {
    if (!tok || tok[0] == '\0') return false;
    char* endp = nullptr;
    long v = strtol(tok, &endp, 10);
    if (*endp != '\0' || v < min_v || v > max_v) return false;
    *out = static_cast<int>(v);
    return true;
}

/**
 * Process one incoming USB CDC command line.
 * Returns true if `reply` was populated and should be written back with `\r\n`.
 */
inline bool process_command_line(
    DeviceModel& m,
    const char* raw_line,
    uint32_t now_ms,
    char* reply,
    size_t reply_size
) {
    reply[0] = '\0';
    if (!raw_line) return false;

    char cmd[32];
    const char* rest = next_token(raw_line, cmd, sizeof(cmd));
    if (cmd[0] == '\0' || cmd[0] == '#') {
        return false;
    }

    // 1. PING [seq] -> PONG [seq]
    if (str_ieq(cmd, "PING")) {
        char seq[32];
        next_token(rest, seq, sizeof(seq));
        if (seq[0] != '\0') {
            snprintf(reply, reply_size, "PONG %s", seq);
        } else {
            snprintf(reply, reply_size, "PONG");
        }
        return true;
    }

    // 2. HELLO / VERSION
    if (str_ieq(cmd, "HELLO") || str_ieq(cmd, "VERSION")) {
        snprintf(
            reply,
            reply_size,
            "OK HELLO proto=2 fw=0.2.0-draft board=esp32-s3-touch-lcd-3.49 res=640x172 slots=%d",
            kNumSlots
        );
        return true;
    }

    // 3. CLEAR -> reset all slots, approval, and hint
    if (str_ieq(cmd, "CLEAR")) {
        m.reset(now_ms);
        snprintf(reply, reply_size, "OK CLEAR");
        return true;
    }

    // 4. SLOT / SLOT_SET <1..6> <state> [name]
    if (str_ieq(cmd, "SLOT") || str_ieq(cmd, "SLOT_SET")) {
        char slot_tok[16];
        char state_tok[24];
        rest = next_token(rest, slot_tok, sizeof(slot_tok));
        rest = next_token(rest, state_tok, sizeof(state_tok));

        int slot_num = 0;
        if (!parse_int_range(slot_tok, 1, kNumSlots, &slot_num)) {
            snprintf(reply, reply_size, "ERR BAD_SLOT expected 1..%d", kNumSlots);
            return true;
        }
        SlotState st = SlotState::STATE_IDLE;
        if (!parse_slot_state(state_tok, &st)) {
            snprintf(reply, reply_size, "ERR BAD_STATE expected RUN|ASK|DONE|ERR|IDLE|GATE");
            return true;
        }

        SlotInfo& slot = m.slots[slot_num - 1];
        bool state_changed = (!slot.assigned) || (slot.state != st);

        char clean_name[kAgentNameMax + 1] = "";
        sanitize_ascii(rest, clean_name, kAgentNameMax, true, false);

        if (strcmp(clean_name, "-") == 0) {
            if (st == SlotState::STATE_IDLE) {
                slot.assigned = false;
                snprintf(slot.name, sizeof(slot.name), "--");
            }
        } else if (clean_name[0] != '\0') {
            slot.assigned = true;
            snprintf(slot.name, sizeof(slot.name), "%s", clean_name);
        } else if (!slot.assigned) {
            if (st == SlotState::STATE_IDLE) {
                snprintf(slot.name, sizeof(slot.name), "--");
            } else {
                slot.assigned = true;
                snprintf(slot.name, sizeof(slot.name), "slot-%d", slot_num);
            }
        }

        slot.state = st;
        if (state_changed) {
            slot.since_ms = now_ms;
        }
        m.ui_dirty = true;
        snprintf(reply, reply_size, "OK SLOT %d %s %s", slot_num, state_name(slot.state), slot.name);
        return true;
    }

    // 5. SLOT_CLEAR <1..6>
    if (str_ieq(cmd, "SLOT_CLEAR")) {
        char slot_tok[16];
        next_token(rest, slot_tok, sizeof(slot_tok));
        int slot_num = 0;
        if (!parse_int_range(slot_tok, 1, kNumSlots, &slot_num)) {
            snprintf(reply, reply_size, "ERR BAD_SLOT expected 1..%d", kNumSlots);
            return true;
        }
        SlotInfo& slot = m.slots[slot_num - 1];
        slot.assigned = false;
        slot.state = SlotState::STATE_IDLE;
        snprintf(slot.name, sizeof(slot.name), "--");
        slot.since_ms = now_ms;
        m.ui_dirty = true;
        snprintf(reply, reply_size, "OK SLOT_CLEAR %d", slot_num);
        return true;
    }

    // 6. APPROVAL / APPROVAL_SHOW
    //    Canonical: APPROVAL <slot:0..6> <tier:low|high|critical> <nonce> <cmd...>
    //    Shorthand: APPROVAL <tier:low|high|critical> <cmd...>
    //    Clear:     APPROVAL CLEAR [nonce]
    if (str_ieq(cmd, "APPROVAL") || str_ieq(cmd, "APPROVAL_SHOW")) {
        char arg1[32];
        const char* after_arg1 = next_token(rest, arg1, sizeof(arg1));
        if (arg1[0] == '\0') {
            snprintf(reply, reply_size, "ERR BAD_APPROVAL missing args");
            return true;
        }
        if (str_ieq(arg1, "CLEAR") || str_ieq(arg1, "OFF") || strcmp(arg1, "-") == 0) {
            m.clear_approval();
            snprintf(reply, reply_size, "OK APPROVAL_CLEAR");
            return true;
        }

        int slot_num = 0;
        RiskTier tier = RiskTier::TIER_NONE;
        char nonce_buf[kNonceMax + 1] = "-";
        const char* summary_src = nullptr;

        if (parse_risk_tier(arg1, &tier)) {
            // Shorthand: APPROVAL <tier> <cmd...>
            slot_num = 0;
            snprintf(nonce_buf, sizeof(nonce_buf), "-");
            summary_src = after_arg1;
        } else if (parse_int_range(arg1, 0, kNumSlots, &slot_num)) {
            // Canonical: APPROVAL <slot> <tier> <nonce> <cmd...>
            char tier_tok[24];
            char nonce_tok[kNonceMax + 1];
            const char* after_tier = next_token(after_arg1, tier_tok, sizeof(tier_tok));
            if (!parse_risk_tier(tier_tok, &tier)) {
                snprintf(reply, reply_size, "ERR BAD_TIER expected low|high|critical");
                return true;
            }
            const char* after_nonce = next_token(after_tier, nonce_tok, sizeof(nonce_tok));
            if (nonce_tok[0] == '\0') {
                snprintf(reply, reply_size, "ERR BAD_APPROVAL missing nonce");
                return true;
            }
            sanitize_ascii(nonce_tok, nonce_buf, kNonceMax, false, false);
            if (nonce_buf[0] == '\0') {
                snprintf(nonce_buf, sizeof(nonce_buf), "-");
            }
            summary_src = after_nonce;
        } else {
            snprintf(reply, reply_size, "ERR BAD_APPROVAL expected <slot> <tier> <nonce> <cmd>");
            return true;
        }

        m.approval.active = true;
        m.approval.slot = static_cast<uint8_t>(slot_num);
        m.approval.tier = tier;
        snprintf(m.approval.nonce, sizeof(m.approval.nonce), "%s", nonce_buf);
        sanitize_ascii(summary_src, m.approval.summary, kCmdSummaryMax, true, true);
        if (m.approval.summary[0] == '\0' && tier != RiskTier::TIER_CRITICAL) {
            snprintf(m.approval.summary, sizeof(m.approval.summary), "(no command summary)");
        }
        // New approval supersedes old transient hint until a new HINT arrives
        m.hint_active = false;
        m.hint[0] = '\0';
        m.ui_dirty = true;

        snprintf(
            reply,
            reply_size,
            "OK APPROVAL %d %s %s",
            slot_num,
            tier_name(tier),
            m.approval.nonce
        );
        return true;
    }

    // 7. APPROVAL_CLEAR [nonce] [reason]
    if (str_ieq(cmd, "APPROVAL_CLEAR")) {
        char nonce_tok[kNonceMax + 1];
        char reason_tok[32];
        rest = next_token(rest, nonce_tok, sizeof(nonce_tok));
        next_token(rest, reason_tok, sizeof(reason_tok));

        if (m.approval.active &&
            nonce_tok[0] != '\0' &&
            strcmp(nonce_tok, "-") != 0 &&
            strcmp(nonce_tok, "*") != 0 &&
            strcmp(nonce_tok, m.approval.nonce) != 0) {
            snprintf(reply, reply_size, "ERR NONCE_MISMATCH shown=%s", m.approval.nonce);
            return true;
        }
        m.clear_approval();
        if (reason_tok[0] != '\0') {
            m.hint_active = true;
            sanitize_ascii(reason_tok, m.hint, kHintMax, true, true);
        }
        snprintf(reply, reply_size, "OK APPROVAL_CLEAR");
        return true;
    }

    // 8. HINT <text...> / APPROVAL_HINT <nonce> <text...>
    if (str_ieq(cmd, "HINT") || str_ieq(cmd, "APPROVAL_HINT")) {
        const char* msg_src = rest;
        if (str_ieq(cmd, "APPROVAL_HINT")) {
            char nonce_tok[kNonceMax + 1];
            msg_src = next_token(rest, nonce_tok, sizeof(nonce_tok));
            if (m.approval.active &&
                nonce_tok[0] != '\0' &&
                strcmp(nonce_tok, "-") != 0 &&
                strcmp(nonce_tok, "*") != 0 &&
                strcmp(nonce_tok, m.approval.nonce) != 0) {
                snprintf(reply, reply_size, "ERR NONCE_MISMATCH shown=%s", m.approval.nonce);
                return true;
            }
        }

        char first_word[16];
        const char* after_first = next_token(msg_src, first_word, sizeof(first_word));
        if ((strcmp(first_word, "-") == 0 || str_ieq(first_word, "CLEAR")) && after_first[0] == '\0') {
            m.clear_hint();
            snprintf(reply, reply_size, "OK HINT_CLEAR");
            return true;
        }

        sanitize_ascii(msg_src, m.hint, kHintMax, true, true);
        if (m.hint[0] == '\0') {
            m.clear_hint();
            snprintf(reply, reply_size, "OK HINT_CLEAR");
        } else {
            m.hint_active = true;
            m.ui_dirty = true;
            snprintf(reply, reply_size, "OK HINT");
        }
        return true;
    }

    // 9. SELECT / FOCUS <0..6 | ->
    if (str_ieq(cmd, "SELECT") || str_ieq(cmd, "FOCUS")) {
        char slot_tok[16];
        next_token(rest, slot_tok, sizeof(slot_tok));
        if (strcmp(slot_tok, "-") == 0 || str_ieq(slot_tok, "NONE")) {
            m.selected_slot = 0;
            m.ui_dirty = true;
            snprintf(reply, reply_size, "OK SELECT 0");
            return true;
        }
        int slot_num = 0;
        if (!parse_int_range(slot_tok, 0, kNumSlots, &slot_num)) {
            snprintf(reply, reply_size, "ERR BAD_SLOT expected 0..%d", kNumSlots);
            return true;
        }
        m.selected_slot = static_cast<uint8_t>(slot_num);
        m.ui_dirty = true;
        snprintf(reply, reply_size, "OK SELECT %d", slot_num);
        return true;
    }

    // 10. HEARTBEAT / HB [seq]
    if (str_ieq(cmd, "HEARTBEAT") || str_ieq(cmd, "HB")) {
        char seq_tok[32];
        next_token(rest, seq_tok, sizeof(seq_tok));
        m.heartbeat_seen = true;
        m.last_heartbeat_ms = now_ms;
        m.ui_dirty = true;
        if (seq_tok[0] != '\0') {
            snprintf(reply, reply_size, "OK HB %s", seq_tok);
        } else {
            snprintf(reply, reply_size, "OK HB");
        }
        return true;
    }

    // 11. BRIGHTNESS <0..255>
    if (str_ieq(cmd, "BRIGHTNESS")) {
        char val_tok[16];
        next_token(rest, val_tok, sizeof(val_tok));
        int val = 0;
        if (!parse_int_range(val_tok, 0, 255, &val)) {
            snprintf(reply, reply_size, "ERR BAD_BRIGHTNESS expected 0..255");
            return true;
        }
        m.brightness = static_cast<uint8_t>(val);
        m.brightness_dirty = true;
        snprintf(reply, reply_size, "OK BRIGHTNESS %d", val);
        return true;
    }

    // 12. STATE / LIST diagnostic dump
    if (str_ieq(cmd, "STATE") || str_ieq(cmd, "LIST")) {
        snprintf(
            reply,
            reply_size,
            "OK STATE s1=%s:%s s2=%s:%s s3=%s:%s s4=%s:%s s5=%s:%s s6=%s:%s appr=%s:%s",
            m.slots[0].name, state_name(m.slots[0].state),
            m.slots[1].name, state_name(m.slots[1].state),
            m.slots[2].name, state_name(m.slots[2].state),
            m.slots[3].name, state_name(m.slots[3].state),
            m.slots[4].name, state_name(m.slots[4].state),
            m.slots[5].name, state_name(m.slots[5].state),
            tier_name(m.approval.tier), m.shown_nonce()
        );
        return true;
    }

    snprintf(reply, reply_size, "ERR UNKNOWN_CMD %s", cmd);
    return true;
}

/**
 * Maps landscape touch coordinates (0..639, 0..171) to slot index 1..6.
 * Returns 0 if the touch lands in the bottom approval/hint bar (y >= slot_area_h).
 */
inline int touch_point_to_slot(uint16_t lx, uint16_t ly, uint16_t ui_w = 640, uint16_t slot_area_h = 136) {
    if (ly >= slot_area_h || ui_w == 0) {
        return 0;
    }
    if (lx >= ui_w) {
        lx = ui_w - 1;
    }
    int slot = static_cast<int>((static_cast<uint32_t>(lx) * kNumSlots) / ui_w) + 1;
    if (slot < 1) slot = 1;
    if (slot > kNumSlots) slot = kNumSlots;
    return slot;
}

/**
 * Formats an outbound KEY event line (without trailing CRLF).
 * Examples:
 *   KEY SLOT 3 DOWN nonce=a1b2c3 ms=12345
 *   KEY APPROVE DOWN nonce=a1b2c3 ms=12400 offline=1
 */
inline void format_key_event(
    const DeviceModel& m,
    const char* key_kind,
    int slot_or_zero,
    bool is_down,
    uint32_t now_ms,
    char* out,
    size_t out_size
) {
    const char* edge = is_down ? "DOWN" : "UP";
    const char* offline_suffix = m.is_hub_offline(now_ms) ? " offline=1" : "";
    if (slot_or_zero >= 1 && slot_or_zero <= kNumSlots) {
        snprintf(
            out,
            out_size,
            "KEY %s %d %s nonce=%s ms=%lu%s",
            key_kind,
            slot_or_zero,
            edge,
            m.shown_nonce(),
            static_cast<unsigned long>(now_ms),
            offline_suffix
        );
    } else {
        snprintf(
            out,
            out_size,
            "KEY %s %s nonce=%s ms=%lu%s",
            key_kind,
            edge,
            m.shown_nonce(),
            static_cast<unsigned long>(now_ms),
            offline_suffix
        );
    }
}

}  // namespace agentdeck
