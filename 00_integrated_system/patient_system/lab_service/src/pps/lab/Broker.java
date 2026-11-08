package pps.lab;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/** Client for the message broker: send / receive / ack / nack over HTTP + JSON (java.net.http, no libraries). */
final class Broker {
    /** The broker answered, but not with success. */
    static final class Refused extends IOException {
        final int status;

        Refused(int status, String body) {
            super("broker answered " + status + ": " + body);
            this.status = status;
        }
    }

    private final String url, client, key;
    private final HttpClient http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(5)).build();

    Broker(String url, String client, String key) {
        this.url = url.replaceAll("/+$", "");
        this.client = client;
        this.key = key;
    }

    String clientName() {
        return client;
    }

    private HttpResponse<String> post(String path, Object json, long timeoutSeconds) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url + path))
                .timeout(Duration.ofSeconds(timeoutSeconds))
                .header("x-service-key", key).header("x-client", client)
                .header("content-type", "application/json").header("accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(Json.write(json))).build();
        HttpResponse<String> r = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (r.statusCode() >= 400) throw new Refused(r.statusCode(), r.body());
        return r;
    }

    /** Send what the outbox holds: destination, body, headers, correlation_id, reply_to. */
    void send(Map<String, Object> spec) throws IOException, InterruptedException {
        Map<String, Object> b = new LinkedHashMap<>();
        b.put("priority", 4);
        b.put("ttl_seconds", null);
        b.putAll(spec);
        post("/send", b, 10);
    }

    /** Wait up to waitSeconds for a message (long poll); null means none arrived. */
    Map<String, Object> receive(String destination, int waitSeconds) throws IOException, InterruptedException {
        Map<String, Object> b = new LinkedHashMap<>();
        b.put("destination", destination);
        b.put("wait", waitSeconds);
        b.put("selector", "");
        HttpResponse<String> r = post("/receive", b, waitSeconds + 10L);
        return r.statusCode() == 204 ? null : Json.asMap(Json.parse(r.body()));
    }

    void ack(long id) throws IOException, InterruptedException {
        post("/ack", Map.of("id", id), 10);
    }

    /** Refuse a message: dead=true sends it to the dead-letter list, otherwise it is offered again after delaySeconds. */
    void nack(long id, String reason, Integer delaySeconds, boolean dead) throws IOException, InterruptedException {
        Map<String, Object> b = new LinkedHashMap<>();
        b.put("id", id);
        b.put("reason", reason);
        b.put("dead", dead);
        if (delaySeconds != null) b.put("delay", delaySeconds);
        post("/nack", b, 10);
    }
}
