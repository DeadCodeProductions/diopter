from dataclasses import dataclass
from bisect import bisect
from typing import Optional


@dataclass
class Range:
    lower_bound: int
    upper_bound: int
    type_: str
    inverse: bool = False


def collect_tags(gimple_vrp: str) -> dict[tuple[int, str], str]:
    tag_var_map = {}
    for lineno, line in enumerate(gimple_vrp.splitlines()):
        if not "ValueRangeTag" in line:
            continue
        line = line.strip().replace("(D)", "")
        try:
            tag, var_paren = line.split("(")
        except:
            continue
        var = var_paren.split(")")[0]
        assert (lineno, tag) not in tag_var_map
        tag_var_map[(lineno, tag.strip())] = var
    return tag_var_map


def find_range_table_begin_locs(gimple_vrp: str) -> list[int]:
    return [
        lineno
        for lineno, line in enumerate(gimple_vrp.splitlines())
        if "Exported global range table:" in line or "Value ranges after" in line
    ]


def search_value_range(
    gimple_lines: list[str], var: str, begin_loc: int, end_loc: int
) -> Optional[Range]:
    for line in gimple_lines[begin_loc:end_loc]:
        line = line.strip()
        if "VARYING" in line:
            continue
        line = line.replace("EQUIVALENCES", "")
        if "*" in line:
            continue
        if line.startswith(var):
            if line.split(":")[0].strip() != var:
                continue
            line = line.split(":")[1].strip()
            assert line[-1] == "]", line
            line = line[:-1]
            type_, range_ = line.split("[")
            type_ = type_.strip()
            range_ = range_.strip()
            if type_[-1] == "~":
                inverse = True
                type_ = type_[:-1].strip()
            else:
                inverse = False
            lb, ub = range_.split(",")
            if ub.strip() == "+INF":
                ub = str(2 ** 64)
            if lb.strip() == "-INF":
                lb = str(-(2 ** 64))
            if lb.strip() == "1B":
                lb = 1
            if type_ == "int32_t":
                type_ = "int"
            if type_ == "uint32_t":
                type_ = "unsigned int"
            if type_ == "uint64_t":
                type_ = "long unsigned int"

            try:
                return Range(int(lb), int(ub), type_, inverse)
            except Exception as e:
                # print(e)
                # print(line)
                # print(f"{lb}, {ub} {type_}")
                return None


def extract_value_ranges(
    gimple_vrp: str,
    tag_var_map: dict[tuple[int, str], str],
    tag_loc_to_table_begin_map: dict[int, int],
) -> dict[str, Range]:
    lines = gimple_vrp.splitlines()
    tag_to_ranges = {}
    for ((tag_loc, tag), var) in tag_var_map.items():
        if r := search_value_range(
            lines, var, tag_loc_to_table_begin_map[tag_loc], tag_loc
        ):
            tag_to_ranges[tag] = r
    return tag_to_ranges


def read_value_ranges(gimple_vrp: str) -> dict[str, Range]:
    tag_var_map = collect_tags(gimple_vrp)
    table_begin_locs = find_range_table_begin_locs(gimple_vrp)
    tag_loc_to_table_begin_map = {}
    for tag_loc, _ in tag_var_map.keys():
        tag_loc_to_table_begin_map[tag_loc] = table_begin_locs[
            bisect(table_begin_locs, tag_loc) - 1
        ]
    return extract_value_ranges(gimple_vrp, tag_var_map, tag_loc_to_table_begin_map)
