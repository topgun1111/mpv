package ai.onnxruntime;
import java.util.*;
public class OrtSession implements AutoCloseable {
  public Map<String, NodeInfo> getInputInfo() throws OrtException {return null;}
  public Map<String, NodeInfo> getOutputInfo() throws OrtException {return null;}
  public Set<String> getInputNames(){return null;}
  public Result run(Map<String, ? extends OnnxTensor> m) throws OrtException {return null;}
  public void close(){}
  public static class Result implements AutoCloseable, Iterable<Map.Entry<String, OnnxValue>> {
    public OnnxValue get(int i){return null;}
    public Optional<OnnxValue> get(String s){return null;}
    public int size(){return 0;}
    public Iterator<Map.Entry<String, OnnxValue>> iterator(){return null;}
    public void close(){}
  }
  public static class SessionOptions implements AutoCloseable {
    public enum OptLevel { NO_OPT, BASIC_OPT, EXTENDED_OPT, ALL_OPT }
    public void setOptimizationLevel(OptLevel l) throws OrtException {}
    public void setIntraOpNumThreads(int n) throws OrtException {}
    public void setInterOpNumThreads(int n) throws OrtException {}
    public void addConfigEntry(String k, String v) throws OrtException {}
    public void addQnn(Map<String,String> m) throws OrtException {}
    public void addCPU(boolean b) throws OrtException {}
    public void close(){}
  }
}
