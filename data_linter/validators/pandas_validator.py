import logging
import pandas as pd
import inspect

from functools import wraps

from datetime import datetime

from arrow_pd_parser.parse import (
    pa_read_csv_to_pandas,
    pa_read_json_to_pandas,
)

from typing import Union

from arrow_pd_parser.pa_pd import arrow_to_pandas

from pyarrow import parquet as pq, fs

from data_linter.validators.base import (
    BaseTableValidator,
)


class PandasValidator(BaseTableValidator):
    """
    Validator using Pandas
    """

    def __init__(
        self,
        filepath: str,
        table_params: dict,
        metadata: dict,
        ignore_missing_cols=False,
    ):
        super().__init__(filepath, table_params, metadata)

        self.ignore_missing_cols = ignore_missing_cols

    @property
    def valid(self):
        return self.response.result["valid"]

    def write_validation_errors_to_log(self, log: logging.Logger):
        table_result = self.response.get_result()
        if not table_result["valid"]:
            failed_cols = self.response.get_names_of_column_failures()
            err_msg = (
                "Table failed validation. "
                f"Col failures: {failed_cols}. "
                "See response error log for more details."
            )
            log.error(err_msg, extra={"context": "VALIDATION"})
            log.debug(str(table_result), extra={"context": "VALIDATION"})

    def read_data_and_validate(self):
        """Reads data from filepath and validates it.

        Data is read using pd_arrow_parser.
        """

        df = self.read_data()  # KARIK TODO
        self.validate_df(df)

    def get_response_dict(self):
        return self.response.get_result()

    def read_data(self) -> pd.DataFrame:  # KARIK TODO
        """
        Reads in the data from the given filepath and returns
        a dataframe
        """

        if self.filepath.startswith("s3://"):
            reader_fs = fs.S3FileSystem(region="eu-west-1")
            fp_for_file_reader = self.filepath.replace("s3://", "", 1)

        else:
            reader_fs = fs.LocalFileSystem()
            fp_for_file_reader = self.filepath

        with reader_fs.open_input_stream(fp_for_file_reader) as f:
            if "csv" in self.metadata.data_format:
                df = pa_read_csv_to_pandas(
                    input_file=f,
                    schema=None,  # Needs actual schema
                    expect_full_schema=False,
                )
            elif "json" in self.metadata.data_format:
                df = pa_read_json_to_pandas(
                    input_file=f,
                    schema=None,  # Needs actual schema
                    expect_full_schema=False,
                )
            elif "parquet" in self.metadata.data_format:
                df = arrow_to_pandas(pq.read_table(f))
            else:
                raise ValueError(
                    f"Unknown data_format in metadata: {self.metadata.data_format}."
                )
        return df

    def validate_df(self, df):  # STEPHEN TODO

        meta_cols = [col for col in self.metadata["columns"] if col["name"] in df]

        for m in meta_cols:
            self.validate_col(df[m["name"]], m)

    def validate_col(self, col, meta_col):

        self.min_max_test(col, meta_col)
        self.min_max_length_test(col, meta_col)
        self.pattern_test(col, meta_col)
        self.enum_test(col, meta_col)
        self.nullable_test(col, meta_col)
        self.datetime_format_test(col, meta_col)
        self.date_format_test(col, meta_col)

    def min_max_test(self, col, meta_col):
        res_dict = _min_max_test(col, meta_col)
        col_name = meta_col["name"]
        if res_dict is not None:
            self.response.add_test_to_col(col_name, "min max numerical", res_dict)

    def min_max_length_test(self, col, meta_col):
        res_dict = _min_max_length_test(col, meta_col)
        col_name = meta_col["name"]
        if res_dict is not None:
            self.response.add_test_to_col(col_name, "min max length", res_dict)

    def pattern_test(self, col, meta_col):
        res_dict = _pattern_test(col, meta_col)
        col_name = meta_col["name"]
        if res_dict is not None:
            self.response.add_test_to_col(col_name, "regex pattern", res_dict)

    def enum_test(self, col, meta_col):
        res_dict = _pattern_test(col, meta_col)
        col_name = meta_col["name"]
        if res_dict is not None:
            self.response.add_test_to_col(col_name, "enum", res_dict)

    def nullable_test(self, col, meta_col):
        res_dict = _nullable_test(col, meta_col)
        col_name = meta_col["name"]
        if res_dict is not None:
            self.response.add_test_to_col(col_name, "nullable", res_dict)

    def datetime_format_test(self, col, meta_col):
        res_dict = _datetime_format_test(col, meta_col)
        col_name = meta_col["name"]
        if res_dict is not None:
            self.response.add_test_to_col(col_name, "datetime", res_dict)

    def date_format_test(self, col, meta_col):
        res_dict = _date_format_test(col, meta_col)
        col_name = meta_col["name"]
        if res_dict is not None:
            self.response.add_test_to_col(col_name, "date", res_dict)


def check_run_validation_for_meta(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        sig = inspect.signature(func)
        argmap = sig.bind_partial(*args, **kwargs).arguments
        mc = argmap.get("meta_col")
        if func.__name__ == "_min_max_test" and _check_meta_has_params(
            ["minimum", "maximum"], mc
        ):
            return func(*args, **kwargs)
        elif func.__name__ == "_min_max_length_test" and _check_meta_has_params(
            ["minLength", "maxLength"], mc
        ):
            return func(*args, **kwargs)
        elif func.__name__ == "_pattern_test" and _check_meta_has_params(
            ["pattern"], mc
        ):
            return func(*args, **kwargs)
        elif func.__name__ == "_enum_test" and _check_meta_has_params(["enum"], mc):
            return func(*args, **kwargs)
        elif func.__name__ == "_nullable_test" and not _check_meta_has_params(
            [None, True], [mc.get("nullable")]
        ):
            return func(*args, **kwargs)
        elif func.__name__ == "_date_format_test" and _check_meta_has_params(
            ["date"], [mc.get("type")]
        ):
            return func(*args, **kwargs)
        elif func.__name__ == "_datetime_format_test" and _check_meta_has_params(
            ["datetime"], [mc.get("type")]
        ):
            return func(*args, **kwargs)
        else:
            pass

    return wrapper


@check_run_validation_for_meta
def _min_max_test(col: pd.Series, meta_col: dict) -> dict:

    col_name = meta_col["name"]
    mi = meta_col.get("minimum")
    ma = meta_col.get("maximum")

    test_inputs = {"column": col_name, "minimum_value": mi, "maximum_value": ma}
    res_dict = _result_dict("min max numerical", test_inputs)

    col_oob = _get_min_max_series_out_of_bounds_col(col, col_name, mi, ma)

    return _fill_res_dict(col, col_oob, res_dict)


@check_run_validation_for_meta
def _min_max_length_test(col: pd.Series, meta_col: dict) -> dict:

    col_name = meta_col["name"]
    mil = meta_col.get("minLength")
    mal = meta_col.get("maxLength")

    test_inputs = {"column": col_name, "minimum_length": mil, "maximum_length": mal}
    res_dict = _result_dict("min max length", test_inputs)

    col_oob = _get_min_max_series_out_of_bounds_col(col.str.len(), col_name, mil, mal)

    return _fill_res_dict(col, col_oob, res_dict)


@check_run_validation_for_meta
def _pattern_test(col: pd.Series, meta_col: dict) -> dict:

    col_name = meta_col["name"]
    pattern = meta_col.get("pattern")

    test_inputs = {"column": col_name, "regex": pattern}

    res_dict = _result_dict("regex", test_inputs)

    col_oob = ~col.str.match(pattern)

    return _fill_res_dict(col, col_oob, res_dict)


@check_run_validation_for_meta
def _enum_test(col: pd.Series, meta_col: dict) -> dict:

    col_name = meta_col["name"]
    enum = meta_col.get("enum")

    test_inputs = {"column": col_name, "enum_value_set": enum}

    res_dict = _result_dict("enum", test_inputs)

    col_oob = ~col.isin(enum)

    return _fill_res_dict(col, col_oob, res_dict)


@check_run_validation_for_meta
def _nullable_test(col: pd.Series, meta_col: dict) -> dict:

    col_name = meta_col.get("name")

    test_inputs = {
        "column": col_name,
    }

    res_dict = _result_dict("nullable", test_inputs)

    col_oob = col.isnull()

    return _fill_res_dict(col, col_oob, res_dict)


@check_run_validation_for_meta
def _date_format_test(col: pd.Series, meta_col) -> dict:

    col_name = meta_col["name"]
    date_format = meta_col.get("date_format", "%Y-%m-%d")
    if date_format.count("%") != 3:
        raise ValueError(f"incorrect formate for date object: {date_format}")

    test_inputs = {"columm": col_name, "date format": date_format}

    res_dict = _result_dict("date format", test_inputs)

    col_conv = pd.Series([_date_or_datetime_conversion(date_format, s) for s in col])

    col_oob = col_conv.isnull()

    return _fill_res_dict(col, col_oob, res_dict)


@check_run_validation_for_meta
def _datetime_format_test(col: pd.Series, meta_col):

    col_name = meta_col["name"]
    date_format = meta_col.get("date_format", "%Y-%m-%d %H:%M:%S")
    if date_format.count("%") < 6 or date_format.count("%") > 9:
        raise ValueError(f"incorrect formate for date object: {date_format}")

    test_inputs = {"columm": col_name, "date format": date_format}

    res_dict = _result_dict("datetime format", test_inputs)

    col_conv = pd.Series([_date_or_datetime_conversion(date_format, s) for s in col])

    col_oob = col_conv.isnull()

    return _fill_res_dict(col, col_oob, res_dict)


def _date_or_datetime_conversion(dt_format: str, date_or_datetime_str: str):
    try:
        return datetime.strptime(date_or_datetime_str, dt_format)
    except ValueError:
        return None


def _result_dict(test_name: str, test_inputs: dict) -> dict:

    d = {
        "valid": None,
        "test_name": test_name,
        "test_inputs": test_inputs,
    }

    return d


def _fill_res_dict(col, col_oob, res_dict) -> dict:

    valid = not col_oob.any()
    res_dict["valid"] = valid

    if not valid:
        unexpected_index_list = col_oob.index[col_oob].tolist()
        unexpected_list = col[unexpected_index_list].tolist()

        res_dict["unexpected_index_list"] = unexpected_index_list
        res_dict["unexpected_list"] = unexpected_list

    return res_dict


def _get_min_max_series_out_of_bounds_col(
    col: pd.Series, colname: str, mi: Union[int, None], ma: Union[int, None]
) -> pd.Series:

    # Test if values out of bounds
    if mi is not None and ma is None:
        col_oob = col < mi
    elif ma is not None and mi is None:
        col_oob = col > ma
    elif mi is not None and ma is not None:
        col_oob = ~col.between(mi, ma)
    else:
        raise ValueError(f"invalid min/max values for column: {colname}")
    return col_oob


def _check_meta_has_params(any_of: list, meta_col: dict):
    return any([a in meta_col for a in any_of])
