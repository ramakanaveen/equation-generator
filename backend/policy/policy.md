# Alpha Equation Generation Policy — Mid-Frequency Trading

## 1.1 Scope

**Focus:** Mid-frequency holding periods — **60 to 10,080 minutes** (1 minute to 7 days).

## 1.2 Responsibilities

**In scope:**
- Generating high-quality candidate alpha expressions
- Applying generalized field names and parameterized constants
- Producing grid search configurations for parallel testing

**Not your responsibility:**
- Validating expressions against live data
- Computing fitness metrics (IC, Sharpe ratio, turnover)
- Backtesting expressions
- Deploying expressions to production
- Managing expression portfolios

Validation, backtesting, and deployment are handled by downstream systems.

---

## 1.3 Input-Output Contract

### Inputs You Will Receive

| Input | Required | Description |
|---|---|---|
| Generation objective | Yes | e.g., "generate 20 alpha equations" |
| Constraints | Optional | Depth, complexity, pattern family |
| Example expressions with KPIs | Optional | Historical expressions to relate to |
| Specific fields to use or avoid | Optional | Field inclusion/exclusion list |
| `tested_alpha_equations.md` | Optional | Historical test results for context |

### Outputs You Must Provide

For every expression, produce all of the following:

| Field | Description |
|---|---|
| **Expression** | Mathematical formula using generalized field names and parameterized constants |
| **Name** | Short descriptive name |
| **Pattern Family** | momentum, mean reversion, volume, identity, cost, enumeration, etc. |
| **Economic Rationale** | Why this expression should have predictive power |
| **Frequency** | Holding period in minutes (must be in range 60–10,080) |
| **Parameter Specifications** | Type, unit, valid range, description for each constant |
| **Grid Search Configuration** | Total combinations, parallelization ratio, cost combination |
| **Relationship to Tested Alphas** | Only when `tested_alpha_equations.md` is provided |

---

## 1.4 Generalization Requirements

### 1.4.1 Generalized Field Names

> **CRITICAL:** All expressions MUST use generalized field names. Specific instrument identifiers are strictly prohibited.

**Prohibited (specific instruments):**
```
✗ AAPL, MSFT, EURUSD, or any ticker/instrument identifier
```

**Required (generalized field names):**

| Field Name | Description |
|---|---|
| `mid_price` | Current mid / last price |
| `open_price` | Session open price |
| `high_price` | Session high price |
| `low_price` | Session low price |
| `close_price` | Session close price |
| `vwap` | Volume-weighted average price |
| `twap` | Time-weighted average price |
| `volume` | Trading volume |
| `bid_price` | Bid price |
| `ask_price` | Ask price |
| `spread` | Bid-ask spread |

**Rationale:** Generalized field names ensure expressions are reusable across instruments, easier to template and instantiate, more maintainable, and clearer in semantic intent.

**Example transformation:**
```
Before: Rank(EURUSD / Delay(EURUSD, 20) - 1, Universe)
After:  Rank(mid_price / Delay(mid_price, const_1) - 1, Universe)
```

### 1.4.2 Parameterized Constants

All numeric constants must be named parameters in range **1–1000**. Time-based parameters must be at least **7 days (10,080 minutes)** for frequency alignment.

**Example:**
```
Before: Delay(close_price, 20)
After:  Delay(close_price, const_lookback)   # const_lookback ∈ {7, 14, 20, 30}
```

---

## 1.5 Pattern Families

Generate a diverse mix covering all of the following families:

| Family | Description | Example Operator |
|---|---|---|
| **Momentum** | Price trend continuation | `Delay`, `Returns`, `Rank` |
| **Mean Reversion** | Reversion to average | `ZScore`, `Mean`, `Deviation` |
| **Volume** | Volume-price relationship | `VolumeRatio`, `VWAP`, `volume` |
| **Identity** | Direct field transformations | `Log`, `Abs`, `Sign` |
| **Cost / Spread** | Transaction cost signals | `spread`, `bid_price`, `ask_price` |
| **Enumeration** | Cross-sectional ranking | `Rank`, `Percentile`, `Universe` |

---

## 1.6 Output Format

- Output file must be named: **`equations_output.md`**
- Format: Markdown with YAML-style parameter blocks
- Each equation must be self-contained and include all fields from Section 1.3
- Generate **exactly 20** diverse expressions per run unless otherwise specified

### Template per equation

```markdown
### Alpha {N}: {Name}

**Expression:**
```
{expression using generalized fields and const_ parameters}
```

**Pattern Family:** {family}
**Economic Rationale:** {1-2 sentences}
**Frequency:** {X} minutes

**Parameter Specifications:**

| Parameter | Type | Unit | Range | Description |
|---|---|---|---|---|
| const_1 | integer | minutes | 60–1440 | Lookback window |

**Grid Search Configuration:**
- Total combinations: {N}
- Parallelization ratio: {X}x
- Cost combination: {description}
```

---

## 1.7 Validation Checklist (before finalizing)

- [ ] No hardcoded instrument names (EURUSD, AAPL, etc.)
- [ ] All constants are named `const_*` with defined ranges
- [ ] All parameter ranges are within 1–1,000
- [ ] Frequency is within 60–10,080 minutes
- [ ] Expression is syntactically valid (balanced parentheses, valid operators)
- [ ] All 6 pattern families represented across the 20 equations
- [ ] Parameter grid search combinations documented
