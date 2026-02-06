# from typing import Callable, Sequence
# import logging




# logger = logging.getLogger(__name__)


# class UserQuit(Exception):
#     """Raised when the user chooses to quit."""

# def prompt_experiment_exclusion(exp_list: Sequence[ExperimentModel], *, input_fn: Callable[[str], str] = input, print_fn: Callable[[str], None] = print,) -> set[int]:
#     """
#     Display paths with 1-based indices. User enters which ones to REMOVE.
#     - Enter (empty) => remove none => return all paths
#     - q / Q => raise UserQuit
#     - spec supports: '1-3,6-9,12'
#     Returns: list of indices of experiments to remove.
#     """
#     if not exp_list:
#         return set()

#     for idx, exp in enumerate(exp_list, start=1):
#         print_fn(f"{idx:>3} - {exp.serie_dir.name}")

#     prompt = (
#         "\nRemove any experiments? "
#         "(e.g. 1-3,6-9 or 2) | Enter = remove none | Q = quit\n> "
#     )

#     while True:
#         raw = input_fn(prompt).strip()
#         if raw == "":
#             return set()
#         if raw.lower() == "q":
#             raise UserQuit()

#         try:
#             removed = _parse_remove_spec(raw, n_items=len(exp_list))
#         except (ValueError, TypeError) as e:
#             logger.error(f"Invalid input: {e}")
#             continue
        
#         return removed
    
# def _parse_remove_spec(spec: str, *, n_items: int) -> set[int]:
#     """
#     Parse a remove spec like: '1-3,6-9,12' into 0-based indices.
#     Accepts whitespace. 1-based input.
#     Args:
#         spec: remove specification string
#         n_items: total number of items (for bounds checking)
#     Returns:
#         Set of 0-based indices to remove.
#     Raises:
#         ValueError: if the spec is invalid or out of range.
#     """
#     spec = spec.strip()
#     if not spec:
#         return set()

#     tokens = [t.strip() for t in spec.split(",") if t.strip()]
#     removed: set[int] = set()

#     for tok in tokens:
#         if "-" in tok:
#             a_str, b_str = [x.strip() for x in tok.split("-", 1)]
#             if not a_str or not b_str:
#                 raise ValueError(f"Invalid range token '{tok}'. Use e.g. 1-3.")
#             a = int(a_str)
#             b = int(b_str)
#             if a <= 0 or b <= 0:
#                 raise ValueError("Indices must be >= 1.")
#             lo, hi = (a, b) if a <= b else (b, a)
#             if hi > n_items:
#                 raise ValueError(f"Index {hi} out of range (max {n_items}).")
#             # convert to 0-based
#             removed.update(range(lo - 1, hi))
#         else:
#             i = int(tok)
#             if i <= 0:
#                 raise ValueError("Indices must be >= 1.")
#             if i > n_items:
#                 raise ValueError(f"Index {i} out of range (max {n_items}).")
#             removed.add(i - 1)

#     return removed