/*
 * The input program of a run: see program.h.
 */
#include "program.h"

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { MAX_WORDS = 8, LINE_LENGTH = 256 };

/* ---- reading ---- */

typedef struct {
    const char *path;
    unsigned line;
    char *error;
    size_t size;
} reader;

static int problem(reader *r, const char *format, ...)
{
    va_list arguments;
    int used = snprintf(r->error, r->size, "%s:%u: ", r->path, r->line);
    va_start(arguments, format);
    if (used >= 0 && (size_t)used < r->size)
        vsnprintf(r->error + used, r->size - (size_t)used, format, arguments);
    va_end(arguments);
    return 0;
}

static int number(reader *r, const char *text, uint64_t maximum,
                  uint64_t *value)
{
    char *end;
    errno = 0;
    unsigned long long parsed = strtoull(text, &end, 0);
    if (errno || end == text || *end || text[0] == '-' || parsed > maximum)
        return problem(r, "not a number up to %llu: %s",
                       (unsigned long long)maximum, text);
    *value = parsed;
    return 1;
}

static int signed_number(reader *r, const char *text, int *value)
{
    char *end;
    errno = 0;
    long parsed = strtol(text, &end, 0);
    if (errno || end == text || *end || parsed < -32768 || parsed > 32767)
        return problem(r, "not a number from -32768 to 32767: %s", text);
    *value = (int)parsed;
    return 1;
}

static int direction(reader *r, const char *word, int *down)
{
    if (!strcmp(word, "down") || !strcmp(word, "up")) {
        *down = !strcmp(word, "down");
        return 1;
    }
    return problem(r, "expected down or up, not %s", word);
}

static int test_of(reader *r, const char *word, wait_test *test)
{
    static const char *names[] = { "eq", "ne", "ge", "lt", "gain" };
    for (unsigned i = 0; i < sizeof names / sizeof *names; i++) {
        if (!strcmp(word, names[i])) {
            *test = (wait_test)i;
            return 1;
        }
    }
    return problem(r, "a wait tests eq, ne, ge, lt or gain, not %s", word);
}

static int in_ram(uint64_t address)
{
    unsigned bank = (unsigned)(address >> 16);
    return bank < IIGS_RAM_BANKS || bank == 0xe0 || bank == 0xe1;
}

/* ADDRESS SIZE VALUE, the start of poke and wait. */
static int location(reader *r, char **words, step *s)
{
    uint64_t address, size, value;
    if (!number(r, words[0], 0xffffff, &address) ||
        !number(r, words[1], 4, &size) || !number(r, words[2], UINT32_MAX,
                                                  &value))
        return 0;
    if (size != 1 && size != 2 && size != 4)
        return problem(r, "a size is 1, 2 or 4 bytes");
    if (!in_ram(address) || !in_ram(address + size - 1))
        return problem(r, "$%06llX is not in RAM",
                       (unsigned long long)address);
    if (size < 4 && value >> (8 * size))
        return problem(r, "%s does not fit in %u bytes", words[2],
                       (unsigned)size);
    s->address = (uint32_t)address;
    s->size = (unsigned)size;
    s->value = (uint32_t)value;
    return 1;
}

/* The action of a step: its words after WHEN. */
static int action(reader *r, char **words, int count, step *s)
{
    const char *kind = words[0];
    uint64_t value;
    static const struct { const char *name; step_kind kind; int words;
                          const char *usage; } forms[] = {
        { "key", STEP_KEY, 3, "key CODE down|up" },
        { "mouse", STEP_MOUSE, 3, "mouse DX DY" },
        { "button", STEP_BUTTON, 3, "button 0|1 down|up" },
        { "shot", STEP_SHOT, 2, "shot NAME" },
        { "note", STEP_NOTE, 2, "note NAME" },
        { "poke", STEP_POKE, 4, "poke ADDRESS SIZE VALUE" },
        { "wait", STEP_WAIT, 6, "wait ADDRESS SIZE TEST VALUE LIMIT" },
        { "stop", STEP_STOP, 1, "stop" },
    };
    const unsigned count_forms = sizeof forms / sizeof *forms;
    unsigned form = 0;
    while (form < count_forms && strcmp(kind, forms[form].name))
        form++;
    if (form == count_forms)
        return problem(r, "unknown input %s", kind);
    if (count != forms[form].words)
        return problem(r, "expected WHEN %s", forms[form].usage);
    s->kind = forms[form].kind;
    switch (s->kind) {
    case STEP_KEY:
        if (!number(r, words[1], 0x7f, &value))
            return problem(r, "an ADB key code is 0-127");
        s->a = (int)value;
        return direction(r, words[2], &s->b);
    case STEP_MOUSE:
        return signed_number(r, words[1], &s->a) &&
               signed_number(r, words[2], &s->b);
    case STEP_BUTTON:
        if (!number(r, words[1], 1, &value))
            return problem(r, "the mouse has buttons 0 and 1");
        s->a = (int)value;
        return direction(r, words[2], &s->b);
    case STEP_SHOT: case STEP_NOTE:
        /* The name of a shot becomes a file name: no directories, no
           surprises; a note's is a word of the log. */
        if (strlen(words[1]) >= PROGRAM_NAME ||
            strspn(words[1], "abcdefghijklmnopqrstuvwxyz"
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") !=
            strlen(words[1]))
            return problem(r, "a name is up to %d letters, digits, "
                           "- and _", PROGRAM_NAME - 1);
        strcpy(s->name, words[1]);
        return 1;
    case STEP_POKE:
        return location(r, words + 1, s);
    case STEP_WAIT: {
        char *parts[3] = { words[1], words[2], words[4] };
        return location(r, parts, s) && test_of(r, words[3], &s->test) &&
               number(r, words[5], UINT32_MAX, &s->limit);
    }
    case STEP_STOP:
        return 1;
    }
    return 0;
}

static int parse_line(reader *r, char *text, step *s, int *empty)
{
    char *words[MAX_WORDS];
    int count = 0;
    char *hash = strchr(text, '#');
    if (hash)
        *hash = 0;
    for (char *word = strtok(text, " \t\r\n"); word;
         word = strtok(NULL, " \t\r\n")) {
        if (count == MAX_WORDS)
            return problem(r, "too many words");
        words[count++] = word;
    }
    *empty = count == 0;
    if (*empty)
        return 1;
    if (count < 2)
        return problem(r, "expected WHEN ACTION");
    memset(s, 0, sizeof *s);
    s->line = r->line;
    s->relative = words[0][0] == '+';
    if (!number(r, words[0] + s->relative, UINT32_MAX, &s->when))
        return 0;
    return action(r, words + 1, count - 1, s);
}

void program_init(program *p)
{
    memset(p, 0, sizeof *p);
}

void program_free(program *p)
{
    free(p->steps);
    program_init(p);
}

int program_read(program *p, const char *path, char *error, size_t size)
{
    reader r = { path, 0, error, size };
    char text[LINE_LENGTH];
    size_t capacity = 0;
    FILE *file = fopen(path, "r");

    program_init(p);
    if (!file) {
        snprintf(error, size, "cannot open %s: %s", path, strerror(errno));
        return 0;
    }
    int ok = 1;
    while (ok && fgets(text, sizeof text, file)) {
        step s;
        int empty;
        r.line++;
        if (!strchr(text, '\n') && !feof(file))
            ok = problem(&r, "a line is longer than %d characters",
                         LINE_LENGTH - 2);
        else if (!parse_line(&r, text, &s, &empty))
            ok = 0;
        else if (!empty) {
            if (p->count == capacity) {
                capacity = capacity ? 2 * capacity : 64;
                step *more = realloc(p->steps, capacity * sizeof *more);
                if (!more)
                    ok = problem(&r, "out of memory");
                else
                    p->steps = more;
            }
            if (ok)
                p->steps[p->count++] = s;
        }
    }
    if (ok && ferror(file)) {
        snprintf(error, size, "cannot read %s", path);
        ok = 0;
    }
    fclose(file);
    if (!ok)
        program_free(p);
    return ok;
}

/* ---- running ---- */

static uint64_t due_of(const program *p, const step *s)
{
    return s->relative ? p->time + s->when : s->when;
}

uint64_t program_due(const program *p)
{
    if (p->next == p->count)
        return UINT64_MAX;
    return p->started ? p->due : due_of(p, &p->steps[p->next]);
}

static uint32_t read_value(const iigs *m, uint32_t address, unsigned size)
{
    uint32_t value = 0;
    for (unsigned i = size; i-- > 0;)
        value = value << 8 | iigs_peek(m, address + i);
    return value;
}

static int passes(const step *s, uint32_t value, uint32_t start)
{
    uint32_t mask = s->size == 4 ? UINT32_MAX : (1u << (8 * s->size)) - 1;
    switch (s->test) {
    case TEST_EQ: return value == s->value;
    case TEST_NE: return value != s->value;
    case TEST_GE: return value >= s->value;
    case TEST_LT: return value < s->value;
    case TEST_GAIN: return ((value - start) & mask) >= s->value;
    }
    return 0;
}

program_result program_step(program *p, iigs *m, const step **current)
{
    if (p->next == p->count)
        return PROGRAM_END;
    const step *s = &p->steps[p->next];
    *current = s;
    if (!p->started) {
        p->due = due_of(p, s);
        if (p->due < p->time)
            return PROGRAM_LATE;
        p->started = 1;
        p->wait_from = p->due;
        if (s->kind == STEP_WAIT)
            p->wait_start = read_value(m, s->address, s->size);
    }
    if (m->frame < p->due)
        return PROGRAM_IDLE;
    if (s->kind == STEP_WAIT &&
        !passes(s, read_value(m, s->address, s->size), p->wait_start)) {
        if (m->frame - p->wait_from >= s->limit)
            return PROGRAM_TIMEOUT;
        p->due = m->frame + 1;
        return PROGRAM_IDLE;
    }
    p->time = m->frame;
    p->next++;
    p->started = 0;

    program_result result = PROGRAM_DONE;
    uint8_t bytes[4];
    switch (s->kind) {
    case STEP_KEY: adb_key(&m->adb, (uint8_t)s->a, s->b); break;
    case STEP_MOUSE: adb_mouse_move(&m->adb, s->a, s->b); break;
    case STEP_BUTTON: adb_mouse_button(&m->adb, s->a, s->b); break;
    case STEP_SHOT: result = PROGRAM_SHOT; break;
    case STEP_NOTE: result = PROGRAM_NOTE; break;
    case STEP_POKE:
        for (unsigned i = 0; i < s->size; i++)
            bytes[i] = (uint8_t)(s->value >> (8 * i));
        iigs_load(m, s->address, bytes, s->size);
        break;
    case STEP_WAIT: break;
    case STEP_STOP: result = PROGRAM_STOP; break;
    }
    return result;
}
