import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * A small JMS-style client for the project's message broker, with no libraries.
 *
 * Connection -> Session -> MessageProducer / MessageConsumer, and Message.acknowledge() / Message.reject(), the same shape as the
 * Java Message Service. The broker speaks HTTP + JSON, so this only needs java.net.http (Java 11 or newer).
 */
public final class PpsMessaging {
    private PpsMessaging() {}

    /** One message received from a queue. Call acknowledge() when you have dealt with it, or reject() to refuse it. */
    public static final class Message {
        public final long id;
        public final String destination;
        public final Map<String, Object> body;
        public final Map<String, Object> headers;
        public final String correlationId;
        public final String replyTo;
        public final int deliveries;
        private final Connection connection;

        Message(Connection connection, Map<String, Object> m) {
            this.connection = connection;
            this.id = ((Number) m.get("id")).longValue();
            this.destination = (String) m.get("destination");
            this.body = Json.asMap(m.get("body"));
            this.headers = Json.asMap(m.get("headers"));
            this.correlationId = (String) m.get("correlation_id");
            this.replyTo = (String) m.get("reply_to");
            this.deliveries = ((Number) m.get("deliveries")).intValue();
        }

        /** Tell the broker this message is finished with. */
        public void acknowledge() throws IOException, InterruptedException {
            connection.post("/ack", Map.of("id", id), 10);
        }

        /** Refuse it. dead=true sends it to the dead-letter list; dead=false offers it again after a short delay. */
        public void reject(boolean dead, String reason) throws IOException, InterruptedException {
            Map<String, Object> b = new LinkedHashMap<>();
            b.put("id", id);
            b.put("dead", dead);
            b.put("reason", reason);
            connection.post("/nack", b, 10);
        }
    }

    public static final class MessageProducer {
        private final Connection connection;
        private final String destination;

        MessageProducer(Connection connection, String destination) {
            this.connection = connection;
            this.destination = destination;
        }

        public void send(Map<String, Object> body, String correlationId, Map<String, String> headers) throws IOException, InterruptedException {
            Map<String, Object> b = new LinkedHashMap<>();
            b.put("destination", destination);
            b.put("body", body);
            b.put("headers", headers == null ? Map.of() : headers);
            b.put("correlation_id", correlationId);
            connection.post("/send", b, 10);
        }
    }

    public static final class MessageConsumer {
        private final Connection connection;
        private final String destination;

        MessageConsumer(Connection connection, String destination) {
            this.connection = connection;
            this.destination = destination;
        }

        /** Wait up to timeoutMillis (at most 25 seconds) for a message; null means none arrived. */
        public Message receive(long timeoutMillis) throws IOException, InterruptedException {
            long wait = Math.min(timeoutMillis, 25_000) / 1000;
            Map<String, Object> b = new LinkedHashMap<>();
            b.put("destination", destination);
            b.put("wait", wait);
            HttpResponse<String> r = connection.post("/receive", b, wait + 10);
            return r.statusCode() == 204 ? null : new Message(connection, Json.asMap(Json.parse(r.body())));
        }
    }

    public static final class Session {
        private final Connection connection;

        Session(Connection connection) {
            this.connection = connection;
        }

        public MessageProducer createProducer(String destination) {
            return new MessageProducer(connection, destination);
        }

        public MessageConsumer createConsumer(String destination) {
            return new MessageConsumer(connection, destination);
        }
    }

    public static final class Connection implements AutoCloseable {
        private final String url, client, key;
        private final HttpClient http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(5)).build();

        /** clientName is the name the broker knows you by (it decides what you may send and receive). */
        public Connection(String brokerUrl, String clientName, String serviceKey) {
            this.url = brokerUrl.replaceAll("/+$", "");
            this.client = clientName;
            this.key = serviceKey;
        }

        public Session createSession() {
            return new Session(this);
        }

        HttpResponse<String> post(String path, Object json, long timeoutSeconds) throws IOException, InterruptedException {
            HttpRequest request = HttpRequest.newBuilder(URI.create(url + path))
                    .timeout(Duration.ofSeconds(timeoutSeconds))
                    .header("x-service-key", key).header("x-client", client)
                    .header("content-type", "application/json").header("accept", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(Json.write(json))).build();
            HttpResponse<String> r = http.send(request, HttpResponse.BodyHandlers.ofString());
            if (r.statusCode() >= 400) throw new IOException("broker answered " + r.statusCode() + ": " + r.body());
            return r;
        }

        @Override
        public void close() {}
    }

    /** Just enough JSON for the broker's messages: objects, arrays, strings, numbers, booleans, null. */
    static final class Json {
        private final String s;
        private int i;

        private Json(String s) {
            this.s = s;
        }

        static Object parse(String text) {
            Json p = new Json(text);
            p.skip();
            Object v = p.value();
            return v;
        }

        @SuppressWarnings("unchecked")
        static Map<String, Object> asMap(Object o) {
            return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
        }

        private void skip() {
            while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
        }

        private Object value() {
            skip();
            char c = s.charAt(i);
            if (c == '{') {
                Map<String, Object> m = new LinkedHashMap<>();
                i++;
                skip();
                if (s.charAt(i) == '}') { i++; return m; }
                while (true) {
                    skip();
                    String k = string();
                    skip();
                    i++; // :
                    m.put(k, value());
                    skip();
                    if (s.charAt(i++) == '}') return m;
                }
            }
            if (c == '[') {
                List<Object> l = new ArrayList<>();
                i++;
                skip();
                if (s.charAt(i) == ']') { i++; return l; }
                while (true) {
                    l.add(value());
                    skip();
                    if (s.charAt(i++) == ']') return l;
                }
            }
            if (c == '"') return string();
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            if (s.startsWith("null", i)) { i += 4; return null; }
            int start = i;
            while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
            String n = s.substring(start, i);
            return n.contains(".") || n.contains("e") || n.contains("E") ? (Object) Double.valueOf(n) : (Object) Long.valueOf(n);
        }

        private String string() {
            StringBuilder b = new StringBuilder();
            i++; // opening quote
            while (s.charAt(i) != '"') {
                char c = s.charAt(i++);
                if (c != '\\') { b.append(c); continue; }
                char e = s.charAt(i++);
                switch (e) {
                    case 'n': b.append('\n'); break;
                    case 't': b.append('\t'); break;
                    case 'r': b.append('\r'); break;
                    case 'b': b.append('\b'); break;
                    case 'f': b.append('\f'); break;
                    case 'u': b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                    default: b.append(e);
                }
            }
            i++; // closing quote
            return b.toString();
        }

        static String write(Object o) {
            StringBuilder b = new StringBuilder();
            write(o, b);
            return b.toString();
        }

        private static void write(Object o, StringBuilder b) {
            if (o == null) b.append("null");
            else if (o instanceof Map) {
                b.append('{');
                boolean first = true;
                for (Map.Entry<?, ?> e : ((Map<?, ?>) o).entrySet()) {
                    if (!first) b.append(',');
                    first = false;
                    write(String.valueOf(e.getKey()), b);
                    b.append(':');
                    write(e.getValue(), b);
                }
                b.append('}');
            } else if (o instanceof Iterable) {
                b.append('[');
                boolean first = true;
                for (Object x : (Iterable<?>) o) {
                    if (!first) b.append(',');
                    first = false;
                    write(x, b);
                }
                b.append(']');
            } else if (o instanceof Number || o instanceof Boolean) b.append(o);
            else {
                b.append('"');
                for (char c : String.valueOf(o).toCharArray()) {
                    if (c == '"' || c == '\\') b.append('\\').append(c);
                    else if (c == '\n') b.append("\\n");
                    else if (c == '\r') b.append("\\r");
                    else if (c == '\t') b.append("\\t");
                    else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
                }
                b.append('"');
            }
        }
    }
}
