package pps.lab;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Just enough JSON for this service (the JDK has none built in): objects, arrays, strings, numbers, booleans, null. */
final class Json {
    private final String s;
    private int i;

    private Json(String s) {
        this.s = s;
    }

    /** Parse a JSON text. Throws IllegalArgumentException when it is not valid JSON. */
    static Object parse(String text) {
        try {
            Json p = new Json(text);
            p.skip();
            Object v = p.value();
            p.skip();
            if (p.i != text.length()) throw new IllegalArgumentException("unexpected text after the JSON value");
            return v;
        } catch (IndexOutOfBoundsException | NumberFormatException e) {
            throw new IllegalArgumentException("not valid JSON");
        }
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
    }

    private void skip() {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
    }

    private void expect(char c) {
        if (s.charAt(i) != c) throw new IllegalArgumentException("expected '" + c + "' at position " + i);
        i++;
    }

    private Object value() {
        skip();
        char c = s.charAt(i);
        if (c == '{') return object();
        if (c == '[') return array();
        if (c == '"') return string();
        if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
        if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
        if (s.startsWith("null", i)) { i += 4; return null; }
        int start = i;
        while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
        if (start == i) throw new IllegalArgumentException("unexpected character '" + c + "' at position " + i);
        String n = s.substring(start, i);
        return n.contains(".") || n.contains("e") || n.contains("E") ? (Object) Double.valueOf(n) : (Object) Long.valueOf(n);
    }

    private Map<String, Object> object() {
        Map<String, Object> m = new LinkedHashMap<>();
        i++;
        skip();
        if (s.charAt(i) == '}') { i++; return m; }
        while (true) {
            skip();
            if (s.charAt(i) != '"') throw new IllegalArgumentException("expected a name at position " + i);
            String k = string();
            skip();
            expect(':');
            m.put(k, value());
            skip();
            char c = s.charAt(i++);
            if (c == '}') return m;
            if (c != ',') throw new IllegalArgumentException("expected ',' or '}' at position " + (i - 1));
        }
    }

    private List<Object> array() {
        List<Object> l = new ArrayList<>();
        i++;
        skip();
        if (s.charAt(i) == ']') { i++; return l; }
        while (true) {
            l.add(value());
            skip();
            char c = s.charAt(i++);
            if (c == ']') return l;
            if (c != ',') throw new IllegalArgumentException("expected ',' or ']' at position " + (i - 1));
        }
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
        } else if (o instanceof Double && (((Double) o).isNaN() || ((Double) o).isInfinite())) b.append("null");
        else if (o instanceof Number || o instanceof Boolean) b.append(o);
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
