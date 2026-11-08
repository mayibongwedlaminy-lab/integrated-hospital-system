"""Compile and run the Java lab analyzer:   python run.py     (needs Java 11 or newer; set PPS_BROKER and PPS_SERVICE_KEY if not default)
The top-level run.py starts it for you when Java is installed."""
import glob, os, shutil, signal, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
java = shutil.which("java")
if not java:
    sys.exit("Java is not installed, so the analyzer cannot run. Install a JDK (version 11 or newer). The rest of the system works without it.")
build = os.path.join(here, "build")
os.makedirs(build, exist_ok=True)
javac = shutil.which("javac")
compiler = [javac] if javac else [java, "-m", "jdk.compiler/com.sun.tools.javac.Main"]  # a JDK's javac, or the compiler inside the JVM
subprocess.check_call(compiler + ["-d", build, *sorted(glob.glob(os.path.join(here, "src", "*.java")))])
os.environ.setdefault("PPS_SERVICE_KEY", "dev-key")
child = subprocess.Popen([java, "-cp", build, "LabAnalyzer"])
signal.signal(signal.SIGTERM, lambda *_: (child.terminate(), sys.exit(0)))  # stopping this wrapper must stop java too
try:
    sys.exit(child.wait())
except KeyboardInterrupt:
    child.terminate()
