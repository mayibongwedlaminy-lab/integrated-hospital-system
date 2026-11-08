"""Run THIS service on its own, for development:   python run.py     (needs Java 11 or newer; a full JDK is not required)

The laboratory is written in Java (JDK classes only, no Maven or Gradle needed). This launcher compiles src/ the first time (and
whenever a source file changed) and then starts pps.lab.Main. The whole system is started by run.py at the top of the project.
Calls to a service need the header  x-service-key: dev-key  (the gateway sends the real key)."""
import glob, os, shutil, signal, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
java = shutil.which("java")
if not java:
    sys.exit("Java is not installed, so the laboratory service cannot run. Install a JDK or JRE, version 11 or newer.")
build = os.path.join(here, "build")
sources = sorted(glob.glob(os.path.join(here, "src", "**", "*.java"), recursive=True))
marker = os.path.join(build, "pps", "lab", "Main.class")
if not os.path.exists(marker) or max(os.path.getmtime(s) for s in sources) > os.path.getmtime(marker):
    os.makedirs(build, exist_ok=True)
    javac = shutil.which("javac")
    compiler = [javac] if javac else [java, "-m", "jdk.compiler/com.sun.tools.javac.Main"]  # a JDK's javac, or the compiler inside the JVM
    print("laboratory: compiling the Java sources...", flush=True)
    subprocess.check_call(compiler + ["-encoding", "UTF-8", "-d", build, *sources])
if "--prepare" in sys.argv:   # the project's start-up asks for this before launching anything
    sys.exit(0)
os.environ.setdefault("PPS_SERVICE_KEY", "dev-key")
child = subprocess.Popen([java, "-cp", build, "pps.lab.Main", os.path.join(here, "service.xml")], cwd=here)
signal.signal(signal.SIGTERM, lambda *_: (child.terminate(), sys.exit(0)))  # stopping this wrapper must stop java too
try:
    sys.exit(child.wait())
except KeyboardInterrupt:
    child.terminate()
