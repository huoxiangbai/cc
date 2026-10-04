import java.nio.file.*;
import java.util.*;
import java.io.*;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.SafeConstructor;
import org.yaml.snakeyaml.LoaderOptions;
import com.fasterxml.jackson.databind.ObjectMapper;
/** Reports only key presence and H2 selection; never logs values or follows imports. */
public class InspectH2Config {
    static Object get(Map<?,?> map,String key){Object value=map;for(String part:key.split("\\.")){value=value instanceof Map<?,?> m?m.get(part):null;}return value;}
    static Map<String,Object> flag(Object value,boolean url){
        String text=Objects.toString(value,"");return Map.of("present",value!=null,"unresolvedPlaceholder",text.contains("${"),"selectsH2",url?text.startsWith("jdbc:h2:"):"h2".equalsIgnoreCase(text)||"org.h2.Driver".equals(text));
    }
    public static void main(String[] args)throws Exception {
        Path root=Path.of(args[0]);List<Map<String,Object>> results=new ArrayList<>();
        for(String name:List.of("application.yml","application-dev.yml","application-test.yml","application-prod.yml")) {
            Path file=root.resolve("Reactor-agent-app/src/main/resources/"+name);Map<String,Object> entry=new TreeMap<>();entry.put("file",name);entry.put("exists",Files.isRegularFile(file));
            if(Files.isRegularFile(file)) {
                try(var in=Files.newInputStream(file)) {
                    List<Map<String,Object>> documents=new ArrayList<>();
                    for(Object raw:new Yaml(new SafeConstructor(new LoaderOptions())).loadAll(in)) {
                        Map<?,?> config=raw instanceof Map<?,?> m?m:Map.of();Map<String,Object> flags=new TreeMap<>();
                        for(String key:List.of("autobots.data-agent.db-config.type","autobots.data-agent.db-config.url","spring.datasource.mysql.driver-class-name","spring.datasource.mysql.url")) flags.put(key,flag(get(config,key),key.endsWith("url")));
                        flags.put("spring.config.import.present",get(config,"spring.config.import")!=null);
                        flags.put("spring.jackson.present",get(config,"spring.jackson")!=null);documents.add(flags);
                    }
                    entry.put("documents",documents);
                }catch(Exception e){entry.put("parseErrorClass",e.getClass().getSimpleName());}
            }
            results.add(entry);
        }
        new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(Path.of(args[1]).toFile(),Map.of("evidence","local file selection only; placeholders/imports/deployment overrides unresolved","profiles",results));
    }
}
