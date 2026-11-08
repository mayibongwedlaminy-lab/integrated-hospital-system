import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Random;

/**
 * The laboratory's automated analyzer, an independent Java system that joins the project only through the message broker.
 *
 *   lab service --(order)--> queue lab.analyzer.orders --> THIS PROGRAM --(result, same correlation id)--> queue lab.analyzer.results --> lab service
 *
 * It knows nothing about the lab's database or REST API. Orders it cannot run are rejected to the dead-letter list.
 * Settings (environment): PPS_BROKER (default http://localhost:8005), PPS_SERVICE_KEY (required), ANALYZER_DELAY_MS (default 1500).
 */
public class LabAnalyzer {
    static String env(String name, String fallback) {
        String v = System.getenv(name);
        return v == null || v.isEmpty() ? fallback : v;
    }

    /** What this analyzer can measure. Returns null for a test it has no method for. */
    static String analyse(String test, Random rnd) {
        switch (test) {
            case "Blood glucose": return String.format("%.1f mmol/L", 4.0 + rnd.nextDouble() * 4.5);
            case "Malaria rapid test": return rnd.nextInt(10) == 0 ? "positive" : "negative";
            default: return null;
        }
    }

    public static void main(String[] args) throws Exception {
        String key = System.getenv("PPS_SERVICE_KEY");
        if (key == null || key.isEmpty()) {
            System.err.println("PPS_SERVICE_KEY is not set (python run.py sets it).");
            System.exit(2);
        }
        long delay = Long.parseLong(env("ANALYZER_DELAY_MS", "1500"));
        Random rnd = new Random();
        try (PpsMessaging.Connection connection = new PpsMessaging.Connection(env("PPS_BROKER", "http://localhost:8005"), "analyzer", key)) {
            PpsMessaging.Session session = connection.createSession();
            PpsMessaging.MessageConsumer orders = session.createConsumer("lab.analyzer.orders");
            System.out.println("Lab analyzer (Java " + System.getProperty("java.version") + ") waiting for orders on lab.analyzer.orders");
            while (true) {
                PpsMessaging.Message order;
                try {
                    order = orders.receive(5_000);
                } catch (IOException e) {
                    System.err.println("Broker not reachable (" + e.getMessage() + "). Retrying in 2 seconds.");
                    Thread.sleep(2000);
                    continue;
                }
                if (order == null) continue;
                String test = String.valueOf(order.body.get("test"));
                try {
                    String result = analyse(test, rnd);
                    if (result == null) {
                        order.reject(true, "no automated method for '" + test + "'");
                        System.out.println("Rejected order for request " + order.body.get("id") + ": no method for " + test);
                        continue;
                    }
                    Thread.sleep(delay); // the machine "runs the sample"
                    Map<String, Object> reply = new LinkedHashMap<>();
                    reply.put("request_id", order.body.get("id"));
                    reply.put("result", result);
                    reply.put("analyzer", "Java lab analyzer");
                    session.createProducer(order.replyTo != null ? order.replyTo : "lab.analyzer.results")
                            .send(reply, order.correlationId, Map.of("type", "AnalyzerResult", "user", "analyzer", "role", "system"));
                    order.acknowledge(); // only after the reply is safely sent: if we crash before this, the order is offered again
                    System.out.println("Request " + order.body.get("id") + " (" + test + "): " + result);
                } catch (IOException e) {
                    System.err.println("Problem handling request " + order.body.get("id") + ": " + e.getMessage());
                    try { order.reject(false, e.getMessage()); } catch (IOException ignored) { /* the broker will offer it again */ }
                }
            }
        }
    }
}
