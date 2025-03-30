awl_context = {
    "@context": [
        {
            "awl": "https://oo-ld.github.io/awl-schema/",
            "ex": "https://example.org/",
            "@base": "https://oo-ld.github.io/awl-schema/",
            "_type": "@type",
            "id": "@id",
            "body": "awl:HasPart",
            "Name": {
                "@id": "awl:Variable",
                "@context": {"@base": "https://example.org/"},
            },
            "targets": "awl:HasTarget",
            "value": {"@id": "awl:HasValue", "@context": {"value": "@value"}},
            "If": {"@id": "awl:If", "@context": {"body": "awl:IfTrue"}},
            "orelse": "awl:IfFalse",
            "test": "awl:HasCondition",
            "comparators": "awl:HasRightHandComparator",
            "ops": "awl:HasOperator",
            "left": "awl:HasLeftHandComparator",
            "func": {
                "@id": "awl:HasFunctionCall",
                "@context": {
                    "@base": "https://example.org/",
                    "Name": "awl:Function",
                    "value": "awl:HasValue",
                },
            },
            "args": "awl:HasArgument",
            "keywords": {
                "@id": "awl:HasKeywordArgument",
                "@context": {"value": "awl:HasValue"},
            },
            "arg": "awl:HasKey",
        }
    ]
}
