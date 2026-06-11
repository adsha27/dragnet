// Dragnet resume template — Typst
// Matches Aditya's current resume style: clean, single column, professional.
// Variables injected by resume.py via typst --input flags or string substitution.

#let name = sys.inputs.at("name", default: "Aditya Sharma")
#let tagline = sys.inputs.at("tagline", default: "Backend / AI Engineer")
#let email = sys.inputs.at("email", default: "aditya0327sharma@gmail.com")
#let phone = sys.inputs.at("phone", default: "+91 98293 68698")
#let github = sys.inputs.at("github", default: "github.com/adsha27")
#let summary = sys.inputs.at("summary", default: "")
#let experience_json = sys.inputs.at("experience", default: "[]")
#let projects_json = sys.inputs.at("projects", default: "[]")
#let skills_json = sys.inputs.at("skills", default: "{}")
#let education_json = sys.inputs.at("education", default: "[]")

#import "resume_lib.typ": *

#set page(
  margin: (x: 0.65in, y: 0.55in),
  paper: "us-letter",
)

#set text(font: "Helvetica Neue", size: 10.5pt, fill: black)
#set par(leading: 0.55em)

// Header
#align(center)[
  #text(size: 22pt, weight: "bold")[#name]
  #linebreak()
  #text(size: 10.5pt)[
    #tagline #h(0.5em) · #h(0.5em)
    #link("mailto:" + email)[#email] #h(0.5em) · #h(0.5em)
    #phone #h(0.5em) · #h(0.5em)
    #link("https://" + github)[#github]
  ]
]

#v(0.3em)
#line(length: 100%, stroke: 0.4pt)
#v(0.1em)

// Summary
#if summary != "" {
  text(size: 10.5pt)[#summary]
  v(0.4em)
}

// Experience section will be rendered from JSON injected at compile time
// (resume.py writes a .typ file directly with the bullets inlined — cleaner than JSON parsing)
