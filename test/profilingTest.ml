(** Copyright (c) 2019-present, Facebook, Inc.

    This source code is licensed under the MIT license found in the
    LICENSE file in the root directory of this source tree. *)

open Core
open OUnit2

open! Test  (* Suppresses logging. *)

module Json = Yojson.Safe

let set_profiling_output path =
  let configuration = Configuration.Analysis.create () in
  let configuration = { configuration with Configuration.Analysis.profiling_output = Some path } in
  Configuration.Analysis.set_global configuration


let test_event_format _ =
  let output_name = Filename.temp_file "profiling" "test" in
  set_profiling_output output_name;
  let assert_event event ~name ~event_type ~timestamp ~tags =
    Sys.remove output_name;
    Profiling.log_event event;
    let canonicalized_event_type =
      event_type
      |> Json.from_string
      |> Json.to_string
    in
    let event_json = Json.from_file output_name in
    let assert_string_equal = assert_equal ~cmp:String.equal ~printer:Fn.id in
    let assert_int_equal = assert_equal ~cmp:Int.equal ~printer:Int.to_string in
    let assert_tag ((key, value), json) =
      match Json.Util.to_list json with
      | [key_json; value_json] ->
          assert_string_equal key (Json.Util.to_string key_json);
          assert_string_equal value (Json.Util.to_string value_json)
      | _ ->
          failwith "Unexpected tag length"
    in
    event_json
    |> Json.Util.member "name"
    |> Json.Util.to_string
    |> assert_string_equal name;
    event_json
    |> Json.Util.member "event_type"
    |> Json.to_string
    |> assert_string_equal canonicalized_event_type;
    event_json
    |> Json.Util.member "timestamp"
    |> Json.Util.to_int
    |> assert_int_equal timestamp;
    event_json
    |> Json.Util.member "tags"
    |> Json.Util.to_list
    |> List.zip_exn tags
    |> List.iter ~f:assert_tag
  in

  assert_event
    (Profiling.Event.create "foo" ~event_type:(Duration 42) ~timestamp:0)
    ~name:"foo"
    ~event_type:"[\"Duration\", 42]"
    ~timestamp:0
    ~tags:[];
  assert_event
    (Profiling.Event.create "bar" ~event_type:(Duration 24) ~timestamp:1 ~tags:["hello", "world"])
    ~name:"bar"
    ~event_type:"[\"Duration\", 24]"
    ~timestamp:1
    ~tags:["hello", "world"]


let () =
  "profiling">:::[
    "event_format">::test_event_format;
  ]
  |> Test.run
