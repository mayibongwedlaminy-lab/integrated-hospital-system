package pps.lab;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;

/**
 * Laboratory organisation service: Java (JDK only) on port 8002.
 *
 * One of the project's three languages: the hospital, specialist, gateway and broker are Python, the pharmacy is Node.js, this is Java.
 * It keeps the same agreement (contract.xml) as every other organisation: REST + JSON, the shared service key, the "who is acting"
 * headers, and messages through the broker. Its tables, endpoints and messages are declared in service.xml, which this program reads.
 *
 *   POST /lab/requests            a doctor orders a test (also arrives as a message on lab.requests when the lab was offline)
 *   PUT  /lab/results/{id}        a technician enters a result (also arrives from the Java analyzer on lab.analyzer.results)
 *   GET  /lab/requests            list, filter with ?patient_id= or ?status=
 *   POST|GET|PUT /lab/staff       the laboratory's own staff
 */
public final class Main {
    private final Config cfg;
    private final Store store;
    private final Broker broker;
    private final String key;
    private volatile boolean running = true;
    private final Object wake = new Object();

    private Main(Config cfg, Store store, Broker broker, String key) {
        this.cfg = cfg;
        this.store = store;
        this.broker = broker;
        this.key = key;
    }

    public static void main(String[] args) throws Exception {
        String key = System.getenv("PPS_SERVICE_KEY");
        if (key == null || key.isEmpty()) {
            System.err.println("PPS_SERVICE_KEY is not set (python run.py sets it).");
            System.exit(2);
        }
        String xml = args.length > 0 ? args[0] : "service.xml";
        Config cfg = new Config(new File(xml));
        String data = System.getenv("PPS_DATA");
        Path dataDir = data != null && !data.isEmpty() ? Path.of(data) : new File(xml).getAbsoluteFile().getParentFile().toPath();
        Store store = new Store(cfg, dataDir);
        Broker broker = cfg.messaging ? new Broker(cfg.broker, cfg.client, key) : null;
        new Main(cfg, store, broker, key).start();
    }

    // ------------------------------------------------------------------ start-up
    private void start() throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", cfg.port), 0);
        server.setExecutor(Executors.newFixedThreadPool(8));
        server.createContext("/", ex -> {
            try {
                route(ex);
            } catch (HttpError e) {
                send(ex, e.status, Map.of("detail", e.detail));
            } catch (IllegalArgumentException e) {
                send(ex, 400, Map.of("detail", "the request body is not valid JSON"));
            } catch (Throwable t) {
                t.printStackTrace();
                send(ex, 500, Map.of("detail", "internal error"));
            } finally {
                ex.close();
            }
        });
        server.start();
        if (broker != null) {
            daemon("outbox-relay", this::relay);
            for (Config.Consume c : cfg.consumes) daemon("consume-" + c.queue, () -> consume(c));
        }
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            running = false;
            synchronized (wake) { wake.notifyAll(); }
            server.stop(0);
        }));
        System.out.println("laboratory service (Java " + System.getProperty("java.version") + ") on http://localhost:" + cfg.port);
    }

    private static void daemon(String name, Runnable r) {
        Thread t = new Thread(r, name);
        t.setDaemon(true);
        t.start();
    }

    // ------------------------------------------------------------------ HTTP
    private void route(HttpExchange ex) throws IOException {
        String supplied = ex.getRequestHeaders().getFirst("x-service-key");   // only the gateway (and sibling services) may call a service
        if (supplied == null || !MessageDigest.isEqual(supplied.getBytes(StandardCharsets.UTF_8), key.getBytes(StandardCharsets.UTF_8))) {
            send(ex, 401, Map.of("detail", "Services accept requests from the gateway only. Use the portal."));
            return;
        }
        String method = ex.getRequestMethod(), path = ex.getRequestURI().getRawPath();
        if (method.equals("GET") && path.equals("/health")) { send(ex, 200, Map.of("ok", true)); return; }
        if (method.equals("GET") && path.equals("/")) { send(ex, 200, overview()); return; }

        boolean pathKnown = false;
        for (Config.Endpoint e : cfg.endpoints) {
            Matcher m = e.pattern.matcher(path);
            if (!m.matches()) continue;
            pathKnown = true;
            if (!e.method.equals(method)) continue;
            String rid = m.groupCount() > 0 ? URLDecoder.decode(m.group(1), StandardCharsets.UTF_8) : null;
            Map<String, Object> body = new LinkedHashMap<>();
            byte[] raw = ex.getRequestBody().readAllBytes();
            if (raw.length > 0) {
                Object parsed = Json.parse(new String(raw, StandardCharsets.UTF_8));
                if (!(parsed instanceof Map)) throw new HttpError(422, "the body must be a JSON object");
                body = Json.asMap(parsed);
            }
            String user = ex.getRequestHeaders().getFirst("x-user");
            Store.Actor actor = user == null || user.isEmpty() ? null : new Store.Actor(user, ex.getRequestHeaders().getFirst("x-role"));
            Object result = execute(e, body, rid, query(ex), actor, null);
            send(ex, 200, result);
            if (broker != null) synchronized (wake) { wake.notifyAll(); }
            return;
        }
        throw new HttpError(pathKnown ? 405 : 404, pathKnown ? "Method Not Allowed" : "Not Found");
    }

    /** Run one endpoint, whether the request came over HTTP or from a message queue. */
    private Object execute(Config.Endpoint e, Map<String, Object> body, String rid, Map<String, String> query, Store.Actor actor, Long messageId) {
        switch (e.action) {
            case "list": return store.list(e.table, query);
            case "get": return store.one(e.table, rid);
            case "insert": return store.insert(e, body, actor, messageId);
            case "update": return store.update(e, rid, body, actor, messageId);
            default: throw new HttpError(501, "action '" + e.action + "' is not supported");
        }
    }

    private static Map<String, String> query(HttpExchange ex) {
        Map<String, String> q = new LinkedHashMap<>();
        String raw = ex.getRequestURI().getRawQuery();
        if (raw == null) return q;
        for (String pair : raw.split("&")) {
            if (pair.isEmpty()) continue;
            int eq = pair.indexOf('=');
            q.put(URLDecoder.decode(eq < 0 ? pair : pair.substring(0, eq), StandardCharsets.UTF_8), eq < 0 ? "" : URLDecoder.decode(pair.substring(eq + 1), StandardCharsets.UTF_8));
        }
        return q;
    }

    private static void send(HttpExchange ex, int status, Object json) throws IOException {
        byte[] out = Json.write(json).getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("content-type", "application/json; charset=utf-8");
        ex.sendResponseHeaders(status, out.length);
        ex.getResponseBody().write(out);
    }

    private Map<String, Object> overview() {
        Map<String, Object> o = new LinkedHashMap<>();
        o.put("service", cfg.name);
        o.put("port", cfg.port);
        o.put("database", cfg.db);
        o.put("language", "Java " + System.getProperty("java.version"));
        List<Object> tables = new ArrayList<>(), endpoints = new ArrayList<>();
        for (String t : cfg.tables.keySet()) {
            String open = "";
            for (Config.Endpoint e : cfg.endpoints) if (e.table.equals(t) && e.action.equals("list")) { open = e.path; break; }
            tables.add(new LinkedHashMap<>(Map.of("table", t, "records", store.count(t), "open", open)));
        }
        Map<String, String> does = Map.of("list", "List records", "get", "Get one record", "insert", "Create a record", "update", "Update a record");
        for (Config.Endpoint e : cfg.endpoints) endpoints.add(new LinkedHashMap<>(Map.of("method", e.method, "path", e.path, "does", does.get(e.action))));
        o.put("tables", tables);
        o.put("endpoints", endpoints);
        if (cfg.messaging) {
            Map<String, Object> m = new LinkedHashMap<>();
            List<Object> receives = new ArrayList<>(), sends = new ArrayList<>();
            for (Config.Consume c : cfg.consumes) receives.add(new LinkedHashMap<>(Map.of("queue", c.queue, "handled_by", c.endpoint)));
            for (Config.Send s : cfg.sends) sends.add(new LinkedHashMap<>(Map.of("after", s.after, "to", s.to, "type", s.type, "only_when", s.when)));
            m.put("receives", receives);
            m.put("sends", sends);
            m.put("waiting_in_outbox", store.outboxSize());
            o.put("messaging", m);
        }
        return o;
    }

    // ------------------------------------------------------------------ messaging
    /** Outbox -> broker, in order. If the broker is down the messages simply wait in the lab's own store. */
    private void relay() {
        while (running) {
            try {
                synchronized (wake) { wake.wait(1000); }
                for (Map<String, Object> row : store.outboxBatch(100)) {
                    @SuppressWarnings("unchecked") Map<String, Object> spec = (Map<String, Object>) row.get("payload");
                    try {
                        broker.send(spec);
                    } catch (Broker.Refused e) {
                        if (e.status >= 500) break;                    // broker trouble: keep it and try again
                        System.err.println("[" + cfg.client + "] broker refused a message to " + spec.get("destination") + ": " + e.getMessage());
                    } catch (IOException e) {
                        break;                                          // broker unreachable: the message stays in the outbox
                    }
                    store.outboxDelete((Long) row.get("id"));
                }
            } catch (InterruptedException e) {
                return;
            } catch (RuntimeException e) {
                System.err.println("[" + cfg.client + "] outbox relay: " + e);
            }
        }
    }

    /** This message can never succeed (bad data): dead-letter it, do not retry. */
    private static final class Permanent extends Exception {
        Permanent(String why) {
            super(why);
        }
    }

    /** Receive forever. A handler that returns = acknowledge; Permanent = dead-letter; anything else = offer again after 2 seconds. */
    private void consume(Config.Consume c) {
        boolean warned = false;
        while (running) {
            Map<String, Object> msg;
            try {
                msg = broker.receive(c.queue, 5);
                warned = false;
            } catch (IOException e) {
                if (!warned) System.err.println("[" + cfg.client + "] cannot receive from " + c.queue + ": " + e.getMessage() + ". Retrying.");
                warned = true;
                sleep(2000);
                continue;
            } catch (InterruptedException e) {
                return;
            }
            if (msg == null) continue;
            long id = ((Number) msg.get("id")).longValue();
            try {
                try {
                    handle(c, msg);
                    broker.ack(id);
                } catch (Permanent p) {
                    broker.nack(id, clip(p.getMessage()), null, true);
                } catch (RuntimeException e) {
                    broker.nack(id, clip(e.getClass().getSimpleName() + ": " + e.getMessage()), 2, false);
                }
            } catch (IOException e) {
                // the broker will offer the message again after its visibility timeout; the handler copes with a repeat
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    private void handle(Config.Consume c, Map<String, Object> m) throws Permanent {
        long id = ((Number) m.get("id")).longValue();
        if (store.alreadyHandled(id)) return;                          // delivered twice: already done
        Config.Endpoint e = cfg.endpoint(c.endpoint);
        Map<String, Object> body = Json.asMap(m.get("body"));
        String rid = null;
        if (c.id.equals("correlation_id")) rid = (String) m.get("correlation_id");
        else if (e.param != null) { Object v = body.get(c.id.isEmpty() ? e.param : c.id); rid = v == null ? null : String.valueOf(v); }
        Map<String, Object> h = Json.asMap(m.get("headers"));
        Object user = h.get("user");
        Store.Actor actor = user == null || String.valueOf(user).isEmpty() ? null : new Store.Actor(String.valueOf(user), String.valueOf(h.getOrDefault("role", "")));
        try {
            execute(e, body, rid, new LinkedHashMap<>(), actor, id);   // the "handled" note is saved in the same write as the change
        } catch (HttpError ex) {
            if (ex.status < 500) throw new Permanent(ex.status + ": " + ex.detail);
            throw ex;
        }
    }

    private static String clip(String s) {
        return s == null ? "" : s.length() > 200 ? s.substring(0, 200) : s;
    }

    private static void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
    }
}
