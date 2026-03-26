# Java Code Generation Policy — Alpha Equations

## Scope

You receive a list of alpha equations (in structured markdown format) and must produce
compilable Java code for each one.

## Output Requirements

For **each equation**, produce a single Java class file:
- Filename: `Alpha_{SanitisedName}.java` (spaces → underscores, alphanumeric only)
- One class per file
- All classes implement the `AlphaExpression` interface (defined below)

## Base Interface (include once, in `AlphaExpression.java`)

```java
public interface AlphaExpression {
    String getName();
    String getFamily();
    double evaluate(MarketData data, java.util.Map<String, Double> params);
    java.util.Map<String, double[]> getDefaultParameterGrid();
}
```

## MarketData Contract

Use this class signature (do not implement body — it will be provided by the runtime):

```java
public class MarketData {
    public double midPrice;
    public double openPrice;
    public double highPrice;
    public double lowPrice;
    public double closePrice;
    public double vwap;
    public double twap;
    public double volume;
    public double bidPrice;
    public double askPrice;
    public double spread;
    public double[] history(String field, int lookback); // returns last N values newest-first
}
```

## Class Template

```java
/**
 * {Name}
 * Pattern Family: {family}
 * Economic Rationale: {rationale}
 * Frequency: {frequency} minutes
 */
public class Alpha_{SanitisedName} implements AlphaExpression {

    @Override
    public String getName() { return "{Name}"; }

    @Override
    public String getFamily() { return "{family}"; }

    @Override
    public double evaluate(MarketData data, java.util.Map<String, Double> params) {
        // Extract named parameters with defaults
        double constX = params.getOrDefault("const_x", DEFAULT_CONST_X);
        // ... implement expression logic using data fields and params
        return result;
    }

    @Override
    public java.util.Map<String, double[]> getDefaultParameterGrid() {
        java.util.Map<String, double[]> grid = new java.util.LinkedHashMap<>();
        grid.put("const_x", new double[]{7, 14, 20, 30});
        // ... one entry per const_ parameter with its range values
        return grid;
    }

    // Private constants (midpoint of each parameter range as default)
    private static final double DEFAULT_CONST_X = 14.0;
}
```

## Rules

1. Every `const_*` parameter from the equation spec must appear in `getDefaultParameterGrid()` with its documented range as the array values
2. Use `data.history(field, n)` to access lookback windows
3. Handle division by zero defensively: return `0.0` when denominator is zero
4. No external library imports — only `java.util.*`
5. Include the Javadoc comment block with Name, Family, Rationale, Frequency
6. Do not add a `main` method

## Output Format

Produce all files in sequence, each delimited clearly:

```
=== FILE: Alpha_{Name}.java ===
{full java class content}
=== END FILE ===
```

Start with `AlphaExpression.java` (the interface), then one file per equation.
