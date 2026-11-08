package pps.lab;

import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

/** Reads service.xml with the JDK's own XML parser: tables, endpoints, and what is sent to and received from the broker. */
final class Config {
    static final class Table {
        final String name;
        final Map<String, String> fields = new LinkedHashMap<>();   // field -> default value
        final String unique;

        Table(Element e) {
            name = e.getAttribute("name");
            for (String f : e.getAttribute("fields").split(",")) {
                int eq = f.indexOf('=');
                fields.put((eq < 0 ? f : f.substring(0, eq)).trim(), eq < 0 ? "" : f.substring(eq + 1));
            }
            unique = e.getAttribute("unique").isEmpty() ? null : e.getAttribute("unique");
        }
    }

    static final class Endpoint {
        final String method, path, table, action, set, hook;
        final List<String> stamps = new ArrayList<>();
        final Pattern pattern;
        final String param;   // the {name} in the path, or null

        Endpoint(Element e) {
            method = e.getAttribute("method");
            path = e.getAttribute("path");
            table = e.getAttribute("table");
            action = e.getAttribute("action");
            set = e.getAttribute("set");
            hook = e.getAttribute("hook");
            for (String s : e.getAttribute("stamp").split(",")) if (!s.isBlank()) stamps.add(s.trim());
            Matcher m = Pattern.compile("\\{(\\w+)}").matcher(path);
            param = m.find() ? m.group(1) : null;
            pattern = Pattern.compile("^" + path.replaceAll("\\{\\w+}", "([^/]+)") + "$");
        }

        String tag() {
            return method + " " + path;
        }
    }

    static final class Send {
        final String after, to, type, when, set, correlation, replyTo;
        final List<String> fields = new ArrayList<>();

        Send(Element e) {
            after = e.getAttribute("after");
            to = e.getAttribute("to");
            type = e.getAttribute("type");
            when = e.getAttribute("when");
            set = e.getAttribute("set");
            correlation = e.getAttribute("correlation");
            replyTo = e.getAttribute("reply_to");
            for (String f : e.getAttribute("fields").split(",")) if (!f.isBlank()) fields.add(f.trim());
        }
    }

    static final class Consume {
        final String queue, endpoint, id;

        Consume(Element e) {
            queue = e.getAttribute("queue");
            endpoint = e.getAttribute("endpoint");
            id = e.getAttribute("id");
        }
    }

    final String name, db, broker, client;
    final int port;
    final Map<String, Table> tables = new LinkedHashMap<>();
    final List<Endpoint> endpoints = new ArrayList<>();
    final List<Send> sends = new ArrayList<>();
    final List<Consume> consumes = new ArrayList<>();
    final boolean messaging;

    Config(File xml) throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        Document doc = f.newDocumentBuilder().parse(xml);
        Element root = doc.getDocumentElement();
        name = root.getAttribute("name");
        db = root.getAttribute("db");
        port = Integer.parseInt(root.getAttribute("port"));
        Element msg = null;
        for (Element e : children(root)) {
            switch (e.getTagName()) {
                case "table": tables.put(e.getAttribute("name"), new Table(e)); break;
                case "endpoint": endpoints.add(new Endpoint(e)); break;
                case "messaging": msg = e; break;
                default: break;
            }
        }
        messaging = msg != null;
        broker = msg == null ? "" : msg.getAttribute("broker");
        client = msg == null ? "" : msg.getAttribute("client");
        if (msg != null) {
            for (Element e : children(msg)) {
                if (e.getTagName().equals("send")) sends.add(new Send(e));
                if (e.getTagName().equals("consume")) consumes.add(new Consume(e));
            }
        }
        for (Endpoint e : endpoints) {   // fail early and clearly, like the Python engine does
            if (!e.hook.isEmpty()) throw new IllegalStateException(e.path + " uses hook '" + e.hook + "' but this Java service has no hooks");
            if (!List.of("list", "get", "insert", "update").contains(e.action)) throw new IllegalStateException(e.path + ": action '" + e.action + "' is not supported by the Java service");
        }
        for (Consume c : consumes) {
            if (endpoint(c.endpoint) == null) throw new IllegalStateException("<consume queue='" + c.queue + "'> names '" + c.endpoint + "' which is not an endpoint in service.xml");
        }
    }

    Endpoint endpoint(String tag) {
        for (Endpoint e : endpoints) if (e.tag().equals(tag)) return e;
        return null;
    }

    private static List<Element> children(Element parent) {
        List<Element> out = new ArrayList<>();
        NodeList nodes = parent.getChildNodes();
        for (int i = 0; i < nodes.getLength(); i++) if (nodes.item(i).getNodeType() == Node.ELEMENT_NODE) out.add((Element) nodes.item(i));
        return out;
    }
}
