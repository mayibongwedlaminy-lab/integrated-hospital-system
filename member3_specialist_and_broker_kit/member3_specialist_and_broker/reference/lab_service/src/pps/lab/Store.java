package pps.lab;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * This organisation's own database. The JDK has no database, and this build had no way to download a JDBC driver, so the data
 * lives in one JSON file (lab.json) that is rewritten atomically after every change: write a temporary file, then rename it over
 * the old one, so a crash never leaves half a file. A change to a record, the messages that announce it, and the note "this
 * message id was handled" are saved together in ONE write, which is what makes the outbox and the idempotent consumer reliable.
 * Fine for a lab's demo load; for production swap this class for JDBC (the rest of the service does not change).
 */
final class Store {
    private static final DateTimeFormatter STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneOffset.UTC);

    private final Config cfg;
    private final Path file;
    private Map<String, List<Map<String, Object>>> rows = new LinkedHashMap<>();
    private Map<String, Long> seq = new LinkedHashMap<>();
    private List<Map<String, Object>> outbox = new ArrayList<>();
    private long outboxSeq = 0;
    private Set<Long> processed = new HashSet<>();

    Store(Config cfg, Path dataDir) throws IOException {
        this.cfg = cfg;
        Files.createDirectories(dataDir);
        this.file = dataDir.resolve(cfg.db);
        load();
    }

    // ------------------------------------------------------------------ reading
    synchronized Map<String, Object> one(String table, String id) {
        if (id != null && id.matches("\\d+")) {
            long n = Long.parseLong(id);
            for (Map<String, Object> r : rows.get(table)) if (((Long) r.get("id")) == n) return new LinkedHashMap<>(r);
        }
        throw new HttpError(404, table + " " + id + " not found");
    }

    synchronized List<Map<String, Object>> list(String table, Map<String, String> query) {
        List<Map<String, Object>> out = new ArrayList<>();
        Map<String, String> known = cfg.tables.get(table).fields;
        for (Map<String, Object> r : rows.get(table)) {
            boolean ok = true;
            for (Map.Entry<String, String> q : query.entrySet()) {
                if (known.containsKey(q.getKey()) && !q.getValue().equals(r.get(q.getKey()))) ok = false;
            }
            if (ok) out.add(new LinkedHashMap<>(r));
        }
        return out;
    }

    synchronized int count(String table) {
        return rows.get(table).size();
    }

    synchronized boolean alreadyHandled(long messageId) {
        return processed.contains(messageId);
    }

    // ------------------------------------------------------------------ writing
    /** Everything is stored as text, as in the other organisations' services. */
    private static String asText(Object v, String field) {
        if (v == null) return null;
        if (v instanceof String) return (String) v;
        if (v instanceof Number) return v.toString();
        if (v instanceof Boolean) return ((Boolean) v) ? "1" : "0";
        throw new HttpError(422, "'" + field + "' must be text or a number");
    }

    synchronized Map<String, Object> insert(Config.Endpoint e, Map<String, Object> body, Actor actor, Long messageId) {
        Config.Table t = cfg.tables.get(e.table);
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", seq.get(e.table) + 1);
        for (Map.Entry<String, String> f : t.fields.entrySet()) row.put(f.getKey(), body.containsKey(f.getKey()) ? asText(body.get(f.getKey()), f.getKey()) : f.getValue());
        if (actor != null) for (String col : e.stamps) row.put(col, actor.user);
        row.put("created", STAMP.format(Instant.now()));
        if (t.unique != null) for (Map<String, Object> other : rows.get(e.table)) if (Objects.equals(other.get(t.unique), row.get(t.unique))) throw new HttpError(409, "record already exists");
        return commit(() -> {
            rows.get(e.table).add(row);
            seq.put(e.table, (Long) row.get("id"));
            announce(e.tag(), row);
            if (messageId != null) processed.add(messageId);
            return new LinkedHashMap<>(row);
        });
    }

    synchronized Map<String, Object> update(Config.Endpoint e, String id, Map<String, Object> body, Actor actor, Long messageId) {
        Map<String, Object> existing = one(e.table, id);
        Config.Table t = cfg.tables.get(e.table);
        Map<String, Object> changes = new LinkedHashMap<>();
        for (Map.Entry<String, Object> b : body.entrySet()) if (t.fields.containsKey(b.getKey())) changes.put(b.getKey(), asText(b.getValue(), b.getKey()));
        for (String kv : e.set.split(",")) if (!kv.isBlank()) changes.put(kv.substring(0, kv.indexOf('=')), kv.substring(kv.indexOf('=') + 1));
        if (actor != null) for (String col : e.stamps) changes.put(col, actor.user);
        changes.entrySet().removeIf(c -> Objects.equals(c.getValue(), existing.get(c.getKey())));
        if (t.unique != null && changes.containsKey(t.unique)) {
            for (Map<String, Object> other : rows.get(e.table)) if (!other.get("id").equals(existing.get("id")) && Objects.equals(other.get(t.unique), changes.get(t.unique))) throw new HttpError(409, "record already exists");
        }
        return commit(() -> {
            Map<String, Object> stored = null;
            for (Map<String, Object> r : rows.get(e.table)) if (r.get("id").equals(existing.get("id"))) stored = r;
            stored.putAll(changes);
            announce(e.tag(), stored);
            if (messageId != null) processed.add(messageId);
            return new LinkedHashMap<>(stored);
        });
    }

    /** Record that a message was handled although it changed nothing (kept for completeness of the idempotent consumer). */
    synchronized void markHandled(long messageId) {
        commit(() -> { processed.add(messageId); return null; });
    }

    // ------------------------------------------------------------------ the outbox
    private static boolean matches(String cond, Map<String, Object> row) {
        for (String c : cond.split(",")) {
            c = c.trim();
            if (c.isEmpty()) continue;
            int eq = c.indexOf('=');
            String k = c.substring(0, eq), v = c.substring(eq + 1);
            boolean notEmpty = k.endsWith("!");
            String have = String.valueOf(notEmpty ? row.get(k.substring(0, k.length() - 1)) : row.get(k));
            if (have.equals("null")) have = "";
            if (notEmpty ? have.equals(v) : !have.equals(v)) return false;
        }
        return true;
    }

    /** Put the messages that &lt;send after="METHOD /path"&gt; asks for into the outbox. Runs inside commit(). */
    private void announce(String tag, Map<String, Object> result) {
        for (Config.Send s : cfg.sends) {
            if (!s.after.equals(tag) || !matches(s.when, result)) continue;
            Map<String, Object> body = new LinkedHashMap<>();
            for (String f : s.fields.isEmpty() ? new ArrayList<>(result.keySet()) : s.fields) body.put(f, result.get(f));
            for (String kv : s.set.split(",")) if (!kv.isBlank()) body.put(kv.substring(0, kv.indexOf('=')), kv.substring(kv.indexOf('=') + 1));
            Map<String, Object> spec = new LinkedHashMap<>();
            spec.put("destination", s.to);
            spec.put("body", body);
            spec.put("headers", s.type.isEmpty() ? new LinkedHashMap<>() : new LinkedHashMap<>(Map.of("type", s.type)));
            spec.put("correlation_id", s.correlation.isEmpty() ? null : String.valueOf(result.get(s.correlation)));
            spec.put("reply_to", s.replyTo.isEmpty() ? null : s.replyTo);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", ++outboxSeq);
            entry.put("payload", spec);
            outbox.add(entry);
        }
    }

    synchronized List<Map<String, Object>> outboxBatch(int limit) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> m : outbox) { if (out.size() >= limit) break; out.add(m); }
        return out;
    }

    synchronized void outboxDelete(long id) {
        commit(() -> { outbox.removeIf(m -> ((Long) m.get("id")) == id); return null; });
    }

    synchronized int outboxSize() {
        return outbox.size();
    }

    // ------------------------------------------------------------------ the file
    private interface Change<T> {
        T apply();
    }

    /** Apply a change in memory, save the whole state atomically; if saving fails, go back to what is on disk. */
    private <T> T commit(Change<T> change) {
        try {
            T out = change.apply();
            save();
            return out;
        } catch (IOException | RuntimeException ex) {
            try { load(); } catch (IOException ignored) { /* keep what we have */ }
            if (ex instanceof RuntimeException) throw (RuntimeException) ex;
            throw new HttpError(500, "could not save: " + ex.getMessage());
        }
    }

    private void save() throws IOException {
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("rows", rows);
        state.put("seq", seq);
        state.put("outbox", outbox);
        state.put("outbox_seq", outboxSeq);
        state.put("processed", new ArrayList<>(processed));
        Path tmp = file.resolveSibling(file.getFileName() + ".tmp");
        Files.write(tmp, Json.write(state).getBytes(StandardCharsets.UTF_8));
        Files.move(tmp, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    @SuppressWarnings("unchecked")
    private void load() throws IOException {
        rows = new LinkedHashMap<>();
        seq = new LinkedHashMap<>();
        outbox = new ArrayList<>();
        processed = new HashSet<>();
        outboxSeq = 0;
        Map<String, Object> state = Files.exists(file) ? Json.asMap(Json.parse(Files.readString(file, StandardCharsets.UTF_8))) : new LinkedHashMap<>();
        Map<String, Object> savedRows = Json.asMap(state.get("rows")), savedSeq = Json.asMap(state.get("seq"));
        for (String table : cfg.tables.keySet()) {
            List<Map<String, Object>> list = new ArrayList<>();
            Object saved = savedRows.get(table);
            if (saved instanceof List) for (Object o : (List<Object>) saved) list.add(Json.asMap(o));
            rows.put(table, list);
            seq.put(table, savedSeq.get(table) instanceof Number ? ((Number) savedSeq.get(table)).longValue() : list.stream().mapToLong(r -> ((Number) r.get("id")).longValue()).max().orElse(0));
        }
        if (state.get("outbox") instanceof List) for (Object o : (List<Object>) state.get("outbox")) outbox.add(Json.asMap(o));
        if (state.get("outbox_seq") instanceof Number) outboxSeq = ((Number) state.get("outbox_seq")).longValue();
        if (state.get("processed") instanceof List) for (Object o : (List<Object>) state.get("processed")) processed.add(((Number) o).longValue());
        for (List<Map<String, Object>> table : rows.values()) for (Map<String, Object> r : table) r.put("id", ((Number) r.get("id")).longValue());
        for (Map<String, Object> m : outbox) m.put("id", ((Number) m.get("id")).longValue());
    }

    /** Who is acting (set by the gateway, or by the headers of a broker message). */
    static final class Actor {
        final String user, role;

        Actor(String user, String role) {
            this.user = user;
            this.role = role == null ? "" : role;
        }
    }
}
