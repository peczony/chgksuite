import json
from collections import Counter, defaultdict

import requests

from chgksuite.common import custom_csv_to_results, compose_4s
from chgksuite.composer.composer_common import BaseExporter


class StatsAdder(BaseExporter):
    @staticmethod
    def patch_question(question, message):
        if "comment" not in question:
            question["comment"] = message
        elif isinstance(question["comment"], str):
            question["comment"] += "\n" + message
        elif isinstance(question["comment"], list):
            if len(question["comment"]) > 1:
                if isinstance(question["comment"][1], list):
                    question["comment"][1].append(message)
                else:
                    question["comment"].append(message)
            else:
                question["comment"].append(message)

    @staticmethod
    def get_tournament_results(id_):
        req = requests.get(
            "https://api.rating.chgk.net"
            + f"/tournaments/{id_}/results.json"
            + "?includeMasksAndControversials=1"
        )
        return req.json()

    def process_tournament(self, results):
        for res in results:
            if not res.get("mask"):
                continue
            self.total_teams += 1
            name = res["current"]["name"]
            mask = list(res["mask"])
            if self.args.question_range:
                start, end = self.args.question_range.split("-")
                start = int(start)
                end = int(end)
            else:
                start = 0
                end = 9999
            qnum = 1
            for i, q in enumerate(mask):
                if not start <= (i + 1) <= end:
                    continue
                if q == "1":
                    self.q_counter[qnum] += 1
                    self.q_to_teams[qnum].add(name)
                qnum += 1

    def export(self, outfilename):
        self.q_to_teams = defaultdict(set)
        self.total_teams = 0
        self.q_counter = Counter()
        if self.args.rating_ids:
            ids = [x.strip() for x in self.args.rating_ids.split(",") if x.strip()]
            for id_ in ids:
                results = self.get_tournament_results(id_)
                self.process_tournament(results)
        elif self.args.custom_csv:
            results = custom_csv_to_results(
                self.args.custom_csv, **json.loads(self.args.custom_csv_args)
            )
            self.process_tournament(results)
        qnumber = 1
        for element in self.structure:
            if element[0] != "Question" or str(element[1].get("number")).startswith(
                "0"
            ):
                continue
            scored_teams = self.q_counter[qnumber]
            label = self.labels["general"]["right_answers_for_stats"]
            share = scored_teams / self.total_teams
            message = (
                f"{label}: {scored_teams}/{self.total_teams} ({round(share * 100)}%)"
            )
            if scored_teams > 0 and scored_teams <= self.args.team_naming_threshold:
                teams = ", ".join(sorted(self.q_to_teams[qnumber]))
                message += f" ({teams})"
            self.patch_question(element[1], message)
            qnumber += 1
        with open(outfilename, "w", encoding="utf8") as f:
            f.write(compose_4s(self.structure, args=self.args))
            self.logger.info(f"Output: {outfilename}")
